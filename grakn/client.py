"""Grakn python client."""
import json
from typing import Any, Optional, Iterator, Union, Dict

import grpc

import grakn_pb2_grpc
import concept_pb2 as grpc_concept
from grakn.blocking_iter import BlockingIter
import grakn_pb2 as grpc_grakn
from grakn_pb2 import TxRequest, TxResponse
from iterator_pb2 import Next

_SCHEMA_CONCEPT_BASE_TYPES = {grpc_concept.MetaType, grpc_concept.RelationshipType, grpc_concept.AttributeType,
                              grpc_concept.EntityType, grpc_concept.Role, grpc_concept.Rule}


def _next_response(responses: Iterator[TxResponse]) -> TxResponse:
    try:
        return next(responses)
    except grpc.RpcError as e:
        raise _convert_grpc_error(e)


class GraknTx:
    """A transaction against a knowledge graph. The transaction ends when its surrounding context closes."""

    def __init__(self, requests: BlockingIter[TxRequest], responses: Iterator[TxResponse]) -> None:
        self._requests = requests
        self._responses = responses

    def _next_response(self) -> TxResponse:
        return _next_response(self._responses)

    def execute(self, query: str, *, infer: Optional[bool] = None) -> Any:
        """Execute a Graql query against the knowledge base

        :param query: the Graql query string to execute against the knowledge base
        :param infer: enable inference
        :return: a list of query results

        :raises: GraknError, GraknConnectionError
        """
        grpc_infer = grpc_grakn.Infer(value=infer) if infer is not None else None
        request = TxRequest(execQuery=grpc_grakn.ExecQuery(query=grpc_grakn.Query(value=query), infer=grpc_infer))
        self._requests.add(request)

        iterator_id = self._next_response().iteratorId

        query_results = []

        while True:
            next_request = TxRequest(next=Next(iteratorId=iterator_id))
            self._requests.add(next_request)
            response = self._next_response()

            if response.HasField('done'):
                break
            else:
                query_results.append(response.queryResult)

        return [self._parse_result(query_result) for query_result in query_results]

    def _parse_result(self, result: grpc_grakn.QueryResult) -> Any:
        if result.HasField('otherResult'):
            return json.loads(result.otherResult)
        else:
            answer = result.answer.answer
            return {var: self._parse_concept(answer[var]) for var in answer}

    def _parse_concept(self, concept: grpc_concept.Concept) -> Dict:
        concept_dict = {'id': concept.id.value}

        if concept.baseType in _SCHEMA_CONCEPT_BASE_TYPES:
            concept_dict['label'] = self._get_label(concept.id)

        return concept_dict

    def _get_label(self, cid: grpc_concept.ConceptId) -> str:
        concept_method = grpc_concept.ConceptMethod(getLabel=grpc_concept.Unit())
        request = TxRequest(runConceptMethod=grpc_grakn.RunConceptMethod(id=cid, conceptMethod=concept_method))
        self._requests.add(request)
        response = self._next_response()
        return response.conceptResponse.label.value

    def commit(self) -> None:
        """Commit the transaction."""
        self._requests.add(TxRequest(commit=grpc_grakn.Commit()))


class GraknTxContext:
    """Contains a GraknTx. This should be used in a `with` statement in order to retrieve the GraknTx"""

    def __init__(self, keyspace: str, stub: grakn_pb2_grpc.GraknStub, timeout) -> None:
        self._requests: BlockingIter = BlockingIter()

        try:
            self._responses: Iterator[TxResponse] = stub.Tx(self._requests, timeout=timeout)
        except grpc.RpcError as e:
            raise _convert_grpc_error(e)

        request = TxRequest(open=grpc_grakn.Open(keyspace=grpc_grakn.Keyspace(value=keyspace), txType=grpc_grakn.Write))
        self._requests.add(request)

        # wait for response from "open"
        _next_response(self._responses)

        self._tx = GraknTx(self._requests, self._responses)

    def __enter__(self) -> GraknTx:
        return self._tx

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self._requests.close()
        # we ask for another response. This tells gRPC we are done
        try:
            _next_response(self._responses)
        except StopIteration:
            pass


class Client:
    """Client to a Grakn knowledge base, identified by a uri and a keyspace."""

    DEFAULT_URI: str = 'localhost:48555'
    DEFAULT_KEYSPACE: str = 'grakn'
    DEFAULT_TIMEOUT = 60

    def __init__(self, uri: str = DEFAULT_URI, keyspace: str = DEFAULT_KEYSPACE, *,
                 timeout: int = DEFAULT_TIMEOUT) -> None:
        channel = grpc.insecure_channel(uri)

        # wait for connection to be ready
        try:
            grpc.channel_ready_future(channel).result(timeout)
        except grpc.FutureTimeoutError as e:
            raise(ConnectionError(e))

        self._stub = grakn_pb2_grpc.GraknStub(channel)
        self._timeout = timeout
        self.uri = uri
        self.keyspace = keyspace

    def execute(self, query: str, *, infer: Optional[bool] = None) -> Any:
        """Execute and commit a Graql query against the knowledge base

        :param query: the Graql query string to execute against the knowledge base
        :param infer: enable inference
        :return: a list of query results

        :raises: GraknError, GraknConnectionError
        """
        with self.open() as tx:
            result = tx.execute(query, infer=infer)
            tx.commit()
        return result

    def open(self) -> GraknTxContext:
        """Open a transaction

        :return: a GraknTxContext that can be opened using a `with` statement
        """
        return GraknTxContext(self.keyspace, self._stub, timeout=self._timeout)


class GraknError(Exception):
    """An exception when executing an operation on a Grakn knowledge base"""
    pass


def _convert_grpc_error(error: grpc.RpcError) -> Union[GraknError, ConnectionError]:
    """Convert an error message from gRPC into a GraknError or a ConnectionError"""
    assert isinstance(error, grpc.Call)
    error_type = next((value for (key, value) in error.trailing_metadata() if key == 'errortype'), None)
    if error_type is not None:
        return GraknError(error.details())
    else:
        return ConnectionError(error)

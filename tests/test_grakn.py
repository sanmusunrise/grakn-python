from grakn.client import Graph, Result
import unittest
import json
from typing import List
from requests import Request
from httmock import urlmatch, HTTMock
from urllib.parse import parse_qs
from urllib.parse import SplitResult

query: str = 'match $x sub concept; limit 3;'

response: List[Result] = [
    {'id': 'a', 'label': 'concept'},
    {'id': 'b', 'label': 'entity'},
    {'id': 'c', 'label': 'resource'}
]

mock_uri: str = 'myfavouriteserver.com'
keyspace: str = 'somesortofkeyspace'


class MockEngine:

    def __init__(self):
        @urlmatch(netloc=mock_uri, path='^/graph/graql$')
        def grakn_mock(url: SplitResult, request: Request):
            self.request = request
            self.params = parse_qs(url.query)
            return json.dumps({'response': response})

        self.httmock: HTTMock = HTTMock(grakn_mock)
        self.request: Request = None
        self.params: dict = None

    def __enter__(self):
        self.httmock.__enter__()

    def __exit__(self, *args, **kwargs):
        self.httmock.__exit__(*args, **kwargs)


class TestGraphConstructor(unittest.TestCase):
    def test_open_accepts_no_arguments(self):
        graph = Graph()
        self.assertEqual(graph.keyspace, 'grakn')
        self.assertEqual(graph.uri, 'http://localhost:4567')

    def test_open_accepts_two_arguments(self):
        graph = Graph('http://www.google.com', 'mykeyspace')
        self.assertEqual(graph.uri, 'http://www.google.com')
        self.assertEqual(graph.keyspace, 'mykeyspace')

    def test_open_accepts_keyword_arguments(self):
        graph = Graph(keyspace='mykeyspace', uri='http://www.google.com')
        self.assertEqual(graph.uri, 'http://www.google.com')
        self.assertEqual(graph.keyspace, 'mykeyspace')


class TestExecute(unittest.TestCase):
    def setUp(self):
        self.graph = Graph(uri=f'http://{mock_uri}', keyspace=keyspace)
        self.engine = MockEngine()

    def test_executing_a_valid_query_returns_expected_response(self):
        with self.engine:
            response = self.graph.execute(query)
            self.assertEqual(response, response)

    def test_executing_a_query_sends_expected_accept_header(self):
        with self.engine:
            self.graph.execute(query)
            headers = self.engine.request.headers
            self.assertEqual(headers['Accept'], 'application/graql+json')

    def test_executing_a_query_sends_query_in_params(self):
        with self.engine:
            self.graph.execute(query)
            self.assertEqual(self.engine.params['query'], [query])

    def test_executing_a_query_sends_keyspace_in_params(self):
        with self.engine:
            self.graph.execute(query)
            self.assertEqual(self.engine.params['keyspace'], [keyspace])

    def test_executing_a_query_sends_infer_in_params(self):
        with self.engine:
            self.graph.execute(query)
            self.assertEqual(self.engine.params['infer'], ['False'])

    def test_executing_a_query_sends_materialise_in_params(self):
        with self.engine:
            self.graph.execute(query)
            self.assertEqual(self.engine.params['materialise'], ['False'])
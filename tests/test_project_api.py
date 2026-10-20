import json, sys, tempfile, threading, unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app


class ProjectApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.old = app.DATA; app.DATA = Path(self.tmp.name); app.init()
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
        self.port = self.server.server_port
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        app.POOL = type(app.POOL)(max_workers=1)
    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); app.DATA = self.old; self.tmp.cleanup()

    def _base(self):
        return f'http://127.0.0.1:{self.port}'

    def _post(self, path, data, host=None, origin=None):
        headers = {'Content-Type': 'application/json'}
        if host: headers['Host'] = host
        if origin: headers['Origin'] = origin
        req = Request(self._base() + path, data=json.dumps(data).encode(), headers=headers)
        return urlopen(req, timeout=10)

    def _get(self, path):
        return urlopen(self._base() + path, timeout=10)

    def test_create_list_get(self):
        res = self._post('/api/projects', {'name': '论文一'})
        self.assertEqual(res.status, 201)
        pid = json.loads(res.read())['id']
        listing = json.loads(self._get('/api/projects').read())
        self.assertTrue(any(p['id'] == pid for p in listing))
        one = json.loads(self._get('/api/projects/' + pid).read())
        self.assertEqual(one['name'], '论文一')

    def test_cross_origin_blocked(self):
        with self.assertRaises(HTTPError) as ctx:
            self._post('/api/projects', {'name': 'x'}, host='evil.example')
        self.assertEqual(ctx.exception.code, 403)
        with self.assertRaises(HTTPError) as ctx:
            self._post('/api/projects', {'name': 'x'}, origin='http://evil.example')
        self.assertEqual(ctx.exception.code, 403)

    def test_artifact_traversal_and_unknown(self):
        pid = json.loads(self._post('/api/projects', {'name': '论文二'}).read())['id']
        for bad in ['/api/projects/%s/artifacts/..%%2F..%%2Fetc%%2Fpasswd' % pid, '/api/projects/%s/artifacts/nope.md' % pid]:
            with self.assertRaises(HTTPError) as ctx:
                self._get(bad)
            self.assertEqual(ctx.exception.code, 404)


if __name__ == '__main__':
    unittest.main()

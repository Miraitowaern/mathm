import importlib.util, unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('build',Path(__file__).parents[1]/'desktop'/'build.py')
build=importlib.util.module_from_spec(spec);spec.loader.exec_module(build)

class BuildInterpreterTest(unittest.TestCase):
    def info(self,version='3.12',prefix='/usr/local',deps=True,sqlite3_file=''):
        return {'version':version,'prefix':prefix,'deps':deps,'sqlite3_file':sqlite3_file}
    def test_rejects_unusable_interpreters(self):
        self.assertIn('conda',build.interpreter_problems(self.info(prefix='/opt/miniconda3')))
        self.assertIn('3.9',build.interpreter_problems(self.info(version='3.9')))
        self.assertIn('缺少',build.interpreter_problems(self.info(deps=False)))
        self.assertIn('无法运行',build.interpreter_problems(None))
    def test_accepts_relocatable_and_rejects_non_system_links(self):
        self.assertEqual(build.interpreter_problems(self.info()),'')
        self.assertTrue(build.relocatable(''))
        self.assertFalse(build.relocatable('/nonexistent/_sqlite3.cpython-312-darwin.so'))

if __name__=='__main__':unittest.main()

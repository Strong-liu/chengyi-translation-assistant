"""Test wiring only: mock Baidu, run real PDF extraction/typesetting/export.

Outputs are deliberately labelled test translations and are not user results.
"""
import argparse
import multiprocessing
import os
from pathlib import Path
from unittest.mock import patch

import run_engine
from baidu_academic import BaiduAcademicClient


if __name__ == '__main__':
    multiprocessing.freeze_support()
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', default=str(Path(__file__).resolve().parent.parent / 'build' / 'offline_engine_output'))
    arguments = parser.parse_args()
    with patch.dict(os.environ, {'BAIDU_APP_ID': 'offline-test-id', 'BAIDU_SECRET': 'offline-test-secret'}):
        with patch.object(BaiduAcademicClient, '_request', lambda self, query: '测试译文：' + query):
            code = run_engine.main(['--input', arguments.input, '--output', arguments.output])
    print('OFFLINE_ENGINE_INTEGRATION_EXIT', code, flush=True)
    raise SystemExit(code)

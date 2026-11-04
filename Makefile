# 零相依的測試與「build」（靜態站無打包，build = 語法與資料完整性檢查）
.PHONY: test test-py test-js build check

test: test-py test-js

test-py:
	python3 -m unittest discover -s tests -t . -v

test-js:
	node --test tests/frontend.test.mjs

build:
	python3 scripts/build_check.py

check: build test

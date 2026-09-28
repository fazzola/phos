.PHONY: openapi

openapi:
	PYTHONPATH=src python -m robot.web.openapi

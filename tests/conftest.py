import os
import sys
import unittest.mock
from dotenv import load_dotenv
import google.auth
import google.cloud.logging
import vertexai

# Load .env file from the project root folder
conftest_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(conftest_dir)
load_dotenv(os.path.join(project_root, ".env"))


# 1. Mock google.auth.default to return dummy credentials and project ID
def mock_default(*args, **kwargs):
    mock_creds = unittest.mock.MagicMock()
    return mock_creds, "mock-project-id"

google.auth.default = mock_default

# 2. Mock vertexai.init
vertexai.init = unittest.mock.MagicMock()

# 3. Mock google.cloud.logging.Client
google.cloud.logging.Client = unittest.mock.MagicMock()

import os
import sys
from pathlib import Path

# Isolated settings for the tests: throwaway database, fake key, no real API call.
os.environ["DATABASE_URL"] = "sqlite:///" + str(Path(__file__).parent / "test_chat.db")
os.environ["RODIUMAI_API_KEY"] = "test-key"
os.environ["RODIUMAI_MODELS"] = "model/a=Model A,model/b"
os.environ["RODIUMAI_MODEL"] = "model/a"
sys.path.insert(0, str(Path(__file__).parent.parent))

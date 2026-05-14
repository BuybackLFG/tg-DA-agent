"""Local development runner that ensures proper PYTHONPATH setup."""
import sys
from pathlib import Path

# Add project root to PYTHONPATH so `src.*` imports resolve
project_root = Path(__file__).resolve().parent
sys.path.insert(0, str(project_root))

if __name__ == "__main__":
    from src.main import main
    import asyncio
    asyncio.run(main())

import sys
import warnings

if any(arg in sys.argv for arg in ["--version", "-v", "--help", "-h"]):
    from .cli import cli
else:
    from urllib3.exceptions import NotOpenSSLWarning

    warnings.filterwarnings("ignore", category=NotOpenSSLWarning)
    from .cli import cli

if __name__ == "__main__":
    cli()

from .cli import main

# Guarded: job processes started with "spawn" re-import the main module.
if __name__ == "__main__":
    raise SystemExit(main())

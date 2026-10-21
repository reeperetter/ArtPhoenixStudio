import multiprocessing

from paint_by_numbers.cli import main

if __name__ == "__main__":
    multiprocessing.freeze_support()      # потрібно для зібраної програми: порівняння варіантів запускає процеси
    raise SystemExit(main())

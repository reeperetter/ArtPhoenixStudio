import sys

from paint_by_numbers.gui.app import main

if __name__ == "__main__":       # охорона потрібна: порівняння варіантів запускає дочірні процеси
    sys.exit(main())

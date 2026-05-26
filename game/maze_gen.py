"""Geração procedural de labirinto via DFS (Depth-First Search randomizado)."""
import random


def generate_maze(width: int, height: int):
    """Retorna (maze, width, height) com células 0=livre, 1=parede, 2=saída."""
    w = width  if width  % 2 == 1 else width  + 1
    h = height if height % 2 == 1 else height + 1

    maze  = [[1] * w for _ in range(h)]
    stack = [(1, 1)]
    maze[1][1] = 0

    while stack:
        x, y = stack[-1]
        neighbors = [
            (x + dx, y + dy, x + dx // 2, y + dy // 2)
            for dx, dy in ((0, -2), (0, 2), (-2, 0), (2, 0))
            if 0 < x + dx < w - 1 and 0 < y + dy < h - 1 and maze[y + dy][x + dx] == 1
        ]
        if neighbors:
            nx, ny, mx, my = random.choice(neighbors)
            maze[my][mx] = 0
            maze[ny][nx] = 0
            stack.append((nx, ny))
        else:
            stack.pop()

    # Coloca a saída no canto oposto ao início
    for y in range(h - 2, 0, -1):
        for x in range(w - 2, 0, -1):
            if maze[y][x] == 0:
                maze[y][x] = 2
                return maze, w, h

    return maze, w, h

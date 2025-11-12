import csv
import sys
import os
import re
import urllib.request
from urllib.parse import urlparse
from collections import deque, defaultdict

#этап 1
def read_config(file_path):
    config = {}
    try:
        with open(file_path, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                key = row.get('parameter')
                value = row.get('value')
                if key:
                    config[key.strip()] = value.strip() if value else ''
    except FileNotFoundError:
        print(f"Ошибка: файл конфигурации '{file_path}' не найден.")
        sys.exit(1)
    except Exception as e:
        print(f"Ошибка при чтении файла: {e}")
        sys.exit(1)
    return config

def validate_config(config):
    errors = []

    if not config.get('package_name'):
        if config.get('mode') != 'test':
            errors.append("Не указано имя анализируемого пакета (package_name).")

    repo_path = config.get('repo_path')
    if not repo_path:
        errors.append("Не указан путь или URL репозитория (repo_path).")
    elif not (repo_path.startswith(('http://','https://','git@')) or os.path.exists(repo_path)):
        errors.append(f"Некорректный путь или URL репозитория: {repo_path}")

    mode = config.get('mode')
    if mode not in ('local', 'remote', 'test'):
        errors.append(f"Некорректный режим работы (mode): {mode}. Используйте 'local', 'remote' или 'test'.")

    try:
        depth = int(config.get('max_depth', 0))
        if depth <= 0:
            errors.append("max_depth должен быть положительным числом.")
    except (ValueError, TypeError):
        errors.append("max_depth должен быть целым числом.")

    if mode == 'test' and not os.path.isfile(repo_path):
        errors.append(f"Файл тестового графа не найден: {repo_path}")

    return errors

#этап 2
def read_local_cargo(path):
    if os.path.isfile(path):
        try:
            with open(path, encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            raise RuntimeError(f"Ошибка чтения файла {path}: {e}")
    candidate = os.path.join(path, 'Cargo.toml')
    if os.path.isfile(candidate):
        try:
            with open(candidate, encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            raise RuntimeError(f"Ошибка чтения файла {candidate}: {e}")

    raise RuntimeError(f"В директории {path} не найден файл Cargo.toml (ожидалось {candidate}).")


def fetch_text(url, timeout=10):
    req = urllib.request.Request(url, headers={'User-Agent':'python-script'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        charset = r.headers.get_content_charset() or 'utf-8'
        return r.read().decode(charset, errors='replace')

def fetch_remote_cargo(repo_url):
    if repo_url.rstrip().endswith('Cargo.toml'):
        try:
            return fetch_text(repo_url)
        except Exception as e:
            raise RuntimeError(f"Не удалось загрузить файл по URL: {e}")

    parsed = urlparse(repo_url)
    if 'github.com' in parsed.netloc:
        parts = [p for p in parsed.path.split('/') if p]
        if len(parts) >= 2:
            owner, repo = parts[0], parts[1]
            if repo.endswith('.git'):
                repo = repo[:-4]
            for branch in ('main','master'):
                raw = f'https://raw.githubusercontent.com/{owner}/{repo}/{branch}/Cargo.toml'
                try:
                    return fetch_text(raw)
                except Exception:
                    continue
            raise RuntimeError("Не найден Cargo.toml в корне репозитория на ветках main/master.")
    raise RuntimeError("Поддерживаются только GitHub URL или прямая ссылка на Cargo.toml для удалённого режима.")

SECTION_RE = re.compile(r'^\s*\[([^\]]+)\]\s*$')
KV_RE = re.compile(r'^\s*([A-Za-z0-9_\-\.]+)\s*=')

def parse_direct_deps(toml_text):
    deps = set()
    current = None
    for ln in toml_text.splitlines():
        line = ln.split('#',1)[0].strip()
        if not line:
            continue
        sec = SECTION_RE.match(line)
        if sec:
            current = sec.group(1).strip()
            if current.startswith('dependencies.'):
                # [dependencies.foo] -> foo
                part = current.split('.',1)[1].strip().strip('"').strip("'")
                if part:
                    deps.add(part)
            continue
        if current == 'dependencies' or (current and current.endswith('.dependencies')):
            m = KV_RE.match(line)
            if m:
                key = m.group(1).strip().strip('"').strip("'")
                if key:
                    deps.add(key)
    return deps

def get_direct_dependencies(cfg):
    repo = cfg.get('repo_path')
    mode = cfg.get('mode')

    if mode == 'local':
        toml = read_local_cargo(repo)
    else:
        toml = fetch_remote_cargo(repo)

    deps = parse_direct_deps(toml)
    return deps

#Этап 3
def parse_test_graph(path):
    if not os.path.isfile(path):
        raise RuntimeError(f"Файл тестового графа не найден: {path}")
    graph = {}
    pattern = re.compile(r'^[A-Z]$')
    try:
        with open(path, encoding='utf-8') as f:
            for raw in f:
                line = raw.split('#',1)[0].strip()
                if not line:
                    continue
                if ':' in line:
                    left, right = line.split(':',1)
                    left = left.strip()
                    if not pattern.match(left):
                        raise RuntimeError(f"Неверное имя узла '{left}' в тестовом файле. Ожидается одна заглавная буква A..Z.")
                    deps = [p.strip() for p in right.split() if p.strip()]
                    for d in deps:
                        if not pattern.match(d):
                            raise RuntimeError(f"Неверное имя зависимости '{d}' у узла '{left}'. Ожидается одна заглавная буква A..Z.")
                    graph[left] = set(deps)
                else:
                    node = line.strip()
                    if not pattern.match(node):
                        raise RuntimeError(f"Неверное имя узла '{node}' в тестовом файле. Ожидается одна заглавная буква A..Z.")
                    graph[node] = set()
    except Exception as e:
        raise RuntimeError(f"Ошибка при чтении тестового графа {path}: {e}")
    return graph

def build_bfs_graph(root, get_deps, max_depth=1):
    graph = defaultdict(set)
    visited = set()
    queue = deque([(root, 0)])
    while queue:
        node, depth = queue.popleft()
        if node in visited:
            continue
        visited.add(node)
        deps = get_deps(node)
        graph[node].update(deps)
        if depth < max_depth:
            for dep in deps:
                if dep not in visited:
                    queue.append((dep, depth + 1))
    return dict(graph)

def print_tree(graph, root, max_depth):
    printed = set()

    def _print(node, depth, path):
        indent = '    ' * depth
        prefix = indent + ('└─ ' if depth > 0 else '')
        if node in path:
            print(f"{prefix}{node} (cycle)")
            return
        if node in printed:
            print(f"{prefix}{node} (visited)")
            return
        print(f"{prefix}{node}")
        printed.add(node)
        if depth >= max_depth:
            return
        for child in sorted(graph.get(node, [])):
            _print(child, depth + 1, path | {node})

    _print(root, 0, set())

#Main
def main():
    #Этап 1
    if len(sys.argv) > 1:
        config_file = sys.argv[1]
    else:
        config_file = 'config.csv'
    config = read_config(config_file)
    errors = validate_config(config)

    if errors:
        print("Обнаружены ошибки конфигурации:")
        for e in errors:
            print(" -", e)
        sys.exit(1)

    print("Конфигурация успешно загружена:")
    for key, value in config.items():
        print(f"{key} = {value}")

    # Этап 2
    print("\nСбор данных: извлекаем прямые зависимости.")
    mode = config.get('mode')
    try:
        if mode in ('local', 'remote'):
            deps = get_direct_dependencies(config)
            if not deps:
                print("Прямые зависимости не найдены.")
            else:
                print("Найденные прямые зависимости (корень):")
                for d in sorted(deps):
                    print(f"- {d}")
        elif mode == 'test':
            deps = parse_test_graph(config.get('repo_path'))
            print("Тестовый граф загружен. Узлы:")
            for node in sorted(deps.keys()):
                children = " ".join(sorted(deps[node])) if deps[node] else "(нет зависимостей)"
                print(f"  {node}: {children}")
        else:
            print("Неизвестный режим работы.")
            sys.exit(1)
    except Exception as e:
        print(f"Ошибка при получении зависимостей: {e}")
        sys.exit(1)

    # Этап 3
    print("\nПостроение графа зависимостей (BFS).")
    max_depth = int(config.get('max_depth', 1))

    if mode == 'test':
        def get_deps(name):
            return deps.get(name, set())

        root = config.get('package_name') or (next(iter(deps.keys())) if deps else None)
        if not root:
            print("Тестовый граф пуст или package_name не указан и не удалось определить корень.")
            sys.exit(1)
        print(f"Корневой пакет: {root}")
    else:
        root = config.get('package_name')

        def get_deps(name):
            if name == root:
                return deps
            return set()

    graph = build_bfs_graph(root, get_deps, max_depth=max_depth)

    print("\nВывод зависимостей:")
    print_tree(graph, root, max_depth)

    total_nodes = set(graph.keys())
    for s in graph.values():
        total_nodes.update(s)
    print(f"\nВсего узлов в собранном графе: {len(total_nodes)}")

if __name__ == "__main__":
    main()

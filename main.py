import csv
import sys
import os
import re
import urllib.request
import urllib.error
from urllib.parse import urlparse

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
        errors.append("Не указано имя анализируемого пакета (package_name).")

    repo_path = config.get('repo_path')
    if not repo_path:
        errors.append("Не указан путь или URL репозитория (repo_path).")
    elif not (repo_path.startswith(('http://','https://','git@')) or os.path.exists(repo_path)):
        errors.append(f"Некорректный путь или URL репозитория: {repo_path}")

    mode = config.get('mode')
    if mode not in ('local', 'remote'):
        errors.append(f"Некорректный режим работы (mode): {mode}. Используйте 'local' или 'remote'.")

    try:
        depth = int(config.get('max_depth', 0))
        if depth <= 0:
            errors.append("max_depth должен быть положительным числом.")
    except (ValueError, TypeError):
        errors.append("max_depth должен быть целым числом.")

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
    try:
        deps = get_direct_dependencies(config)
    except Exception as e:
        print(f"Ошибка при получении зависимостей: {e}")
        sys.exit(1)

    if not deps:
        print("Прямые зависимости не найдены.")
    else:
        print("Найденные прямые зависимости:")
        for d in sorted(deps):
            print(f"- {d}")

if __name__ == "__main__":
    main()

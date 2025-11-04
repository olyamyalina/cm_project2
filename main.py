import csv
import sys
import os

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
    elif not (repo_path.startswith(('http', 'git@')) or os.path.exists(repo_path)):
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

def main():
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

if __name__ == "__main__":
    main()

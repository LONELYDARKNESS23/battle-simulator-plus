# Подготовка и загрузка на GitHub

Проект готовится как отдельный репозиторий из папки `battle-simulator-plus`. Родительская игра и локальная копия `original/` в него не включаются.

## Что публикуется

Исходники игры, тесты, шаблон конфигурации, документация, снимок интерфейса и GitHub Actions. В `.gitignore` исключены настоящая конфигурация, сохранения, `.env`, виртуальные среды, кеши, логи и локальные результаты проверки.

Для передачи исходников без служебных файлов:

```sh
python tools/build_release.py
```

Готовые ZIP и SHA-256 находятся в `dist/`. Внутри архива — самодостаточная папка с `START_GAME.bat` / `START_GAME.sh`; дополнительная установка библиотек не нужна. Архив можно распаковать и использовать как основу нового репозитория.

## Первый push

Создайте пустой репозиторий на GitHub: без автоматически создаваемых README, `.gitignore` и LICENSE. Название и публичность выберите сами. Затем в папке игры:

```sh
git init -b main
git add .
git diff --cached --check
git status --short
```

Перед коммитом проверьте свою Git-идентичность:

```sh
git config user.name
git config user.email
```

Если там остались шаблонные значения, задайте реальные значения только для этого репозитория (или ваш GitHub noreply email):

```sh
git config --local user.name "Ваше имя"
git config --local user.email "Ваш email для коммитов"
```

После проверки файлов:

```sh
git commit -m "Release RIFT 1.0.0"
git remote add origin https://github.com/ВАШ_АККАУНТ/ВАШ_РЕПОЗИТОРИЙ.git
git push -u origin main
```

Замените адрес на адрес созданного репозитория. Если `origin` уже существует, сначала проверьте `git remote -v`; не добавляйте второй remote с тем же именем.

После push во вкладке Actions запустятся настроенные проверки. Workflow использует официальные [checkout](https://github.com/actions/checkout), [setup-python](https://github.com/actions/setup-python) и [setup-node](https://github.com/actions/setup-node), с доступом только на чтение содержимого.

## Выпуск версии

После успешных проверок можно создать тег `v1.0.0`, отправить его и прикрепить ZIP и файл `.sha256` к GitHub Release. Описание выпуска — в [CHANGELOG.md](../CHANGELOG.md).

Лицензия пока не выбрана. По просьбе владельца проекта LICENSE отсутствует.

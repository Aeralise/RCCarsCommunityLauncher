# Настройка GitHub для обновлений RC Cars Launcher

Лаунчер проверяет **опубликованный GitHub Release**, а не просто последний commit в исходниках. Он обращается к публичному API `GET https://api.github.com/repos/OWNER/REPOSITORY/releases/latest` и прежде всего ищет asset `RCCarsLauncher_Portable.zip`. Это важно для сборки PyInstaller `--onedir`: требуется обновлять не только EXE, но и папку `_runtime` с Qt/Python DLL. Старый asset `RCCarsLauncher.exe` поддерживается как совместимость с прежними one-file-релизами, но новые релизы должны содержать полный ZIP-пакет.

Официальная документация GitHub: [Creating/managing releases](https://docs.github.com/en/repositories/releasing-projects-on-github/managing-releases-in-a-repository) и [REST API — latest release](https://docs.github.com/en/rest/releases/releases#get-the-latest-release).

## 1. Создать репозиторий

1. Войди на [github.com](https://github.com/) и нажми **+ → New repository**.
2. Назови репозиторий, например `RCCarsLauncher`. В этом случае адрес будет `https://github.com/Aeralise/RCCarsLauncher` только если владельцем выбран аккаунт `Aeralise`; в противном случае подставь свой username.
3. Для публичного лаунчера лучше выбрать **Public**: публичные опубликованные Releases можно читать без токена. Не добавляй секреты, токены, личные данные или игровые файлы, на распространение которых нет прав.
4. Можно добавить `README.md` и `.gitignore` (Python), либо создать пустой репозиторий и отправить содержимое проекта из папки `RCCarsLauncher`.

## 2. Отправить исходники

Самый простой вариант — GitHub Desktop:

1. Установи [GitHub Desktop](https://desktop.github.com/), выбери **File → Add local repository** или **Create a New Repository**.
2. Укажи папку проекта `RCCarsLauncher` — там должны лежать `launcher.py`, `rccars_launcher/`, `rccars_pack_tool.py`, `requirements.txt`, `build_exe.bat`, `README.md` и `launcher_config.json`.
3. Создай commit, например `Initial launcher source`, затем нажми **Publish repository** и выбери созданный репозиторий.

Альтернатива через Git в терминале из папки проекта:

```bat
git init
git add .
git commit -m "Initial RC Cars Launcher source"
git branch -M main
git remote add origin https://github.com/OWNER/RCCarsLauncher.git
git push -u origin main
```

Замени `OWNER/RCCarsLauncher` на фактического владельца и имя репозитория. Если репозиторий уже инициализирован, повторно `git init` не требуется.

## 3. Прописать репозиторий лаунчера

Открой `launcher_config.json` рядом с `RCCarsLauncher.exe` и задай значение `launcher_update_repo` в формате `OWNER/REPOSITORY` — без `https://`, без `.git` и без `/releases`:

```json
{
  "launcher_update_repo": "OWNER/RCCarsLauncher",
  "homepage_url": "https://github.com/OWNER/RCCarsLauncher"
}
```

Можно указать это же значение на вкладке **Settings & Updates → GitHub repository for launcher releases** и нажать **Save**. Конфигурация находится рядом с EXE, поэтому её можно менять без пересборки приложения. Не публикуй разные пользовательские конфиги в исходниках, если они содержат персональные значения.

## 4. Собрать EXE для релиза

На Windows 10/11 установи Python 3.11/3.12. Перед сборкой помести пользовательскую иконку в файл `launcher_icon.ico` в корне проекта (если иконка нужна). Запусти `build_exe.bat`. После успешной сборки проверь `dist\RCCarsLauncher\RCCarsLauncher.exe` запуском на тестовой папке игры. Рядом будет создан `dist\RCCarsLauncher_Portable.zip`; он содержит EXE и `_runtime` на корневом уровне архива.

## 5. Создать первый Release с пакетом лаунчера

1. Открой репозиторий на GitHub и перейди в **Releases → Draft a new release** (или **Create a new release**).
2. Создай tag, например `v0.1.6`, укажи его для ветки `main` и задай заголовок `RC Cars Launcher 0.1.6`.
3. Добавь release notes: ключевые изменения и известные ограничения.
4. Перетащи **`dist\RCCarsLauncher_Portable.zip`** в область прикрепления файлов релиза. Не перепаковывай папку так, чтобы внутри ZIP появился лишний уровень вложенности; архив должен содержать `RCCarsLauncher.exe` и `_runtime\` прямо в корне. Можно дополнительно приложить `RCCarsLauncher.exe` для ручного запуска, но автообновление предпочитает ZIP-пакет.
5. Нажми **Publish release**. Оставь release опубликованным, не Draft и не Pre-release: endpoint `releases/latest` их не рассматривает как latest stable release.
6. В установленном лаунчере открой **Settings & Updates → Check for launcher updates**. Убедись, что репозиторий сохранён, новая версия определяется и в качестве asset выбран `RCCarsLauncher_Portable.zip`.

Не нужно загружать EXE в обычный список файлов исходников: для текущего updater нужен именно asset опубликованного Release.

## 6. Как выпускать следующие версии

При следующем обновлении:

1. В `rccars_launcher/ui.py` увеличь `APP_VERSION` на следующую версию, например `0.1.6` → `0.1.7`.
2. Обнови `CHANGELOG.md` и при необходимости `README.md`.
3. Запусти тесты: `py -3 -m pytest -q`.
4. Собери новую папку приложения на Windows и протестируй её. Скрипт создаст `RCCarsLauncher_Portable.zip` автоматически.
5. Создай новый Release с новым tag, например `v0.1.7`, и прикрепи новый `RCCarsLauncher_Portable.zip`.

При проверке лаунчер сравнивает числа в версии тега с `APP_VERSION`. Для предсказуемого сравнения используй теги вида `vMAJOR.MINOR.PATCH`: `v0.1.6`, `v0.2.0`, `v1.0.0`.

## Важные детали

- Не загружай токен GitHub в `launcher_config.json`: для публичного репозитория он не нужен.
- Убедись, что `RCCarsLauncher_Portable.zip` действительно приложен к Release. Один лишь source-code ZIP, автоматически генерируемый GitHub, не подходит для автообновления.
- Если проверка обновлений не находит пакет, проверь именно опубликованный **latest stable Release** и наличие `RCCarsLauncher_Portable.zip` среди Assets.
- Автообновление заменяет EXE и `_runtime` после завершения приложения. Существующие `data`, `launcher_config.json`, `social_links.json` и `Tools` сохраняются. Обновляющий ZIP должен содержать только нужный пакет; скрипт извлекает только EXE и `_runtime`.
- Первую версию лаунчера нужно скачать/установить вручную. Встроенное автообновление начинает работать после того, как настроен репозиторий и опубликован Release с `RCCarsLauncher_Portable.zip`.

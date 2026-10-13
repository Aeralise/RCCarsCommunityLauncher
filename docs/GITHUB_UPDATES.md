# Настройка GitHub для обновлений RC Cars Launcher

Лаунчер проверяет **опубликованный GitHub Release**, а не просто последний commit в исходниках. Он обращается к публичному API `GET https://api.github.com/repos/OWNER/REPOSITORY/releases/latest` и ищет среди файлов релиза Windows-файл с расширением `.exe` (предпочтительное имя — `RCCarsLauncher.exe`). Поэтому основной код можно хранить в репозитории, но для автоматического обновления обязательно публиковать собранный EXE как asset релиза.

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

На Windows 10/11 установи Python 3.11/3.12. Перед сборкой помести пользовательскую иконку в файл `launcher_icon.ico` в корне проекта (если иконка нужна). Запусти `build_exe.bat`. После успешной сборки проверь `dist\RCCarsLauncher.exe` запуском на тестовой папке игры.

## 5. Создать первый Release с EXE

1. Открой репозиторий на GitHub и перейди в **Releases → Draft a new release** (или **Create a new release**).
2. Создай tag, например `v0.1.3`, укажи его для ветки `main` и задай заголовок `RC Cars Launcher 0.1.3`.
3. Добавь release notes: ключевые изменения и известные ограничения.
4. Перетащи **`dist\RCCarsLauncher.exe`** в область прикрепления файлов релиза. Имя файла должно быть `RCCarsLauncher.exe` (это имя предпочитает текущий updater).
5. Нажми **Publish release**. Оставь release опубликованным, не Draft и не Pre-release: endpoint `releases/latest` их не рассматривает как latest stable release.
6. В установленном лаунчере открой **Settings & Updates → Check for launcher updates**. Убедись, что репозиторий сохранён и новая версия определяется.

Не нужно загружать EXE в обычный список файлов исходников: для текущего updater нужен именно asset опубликованного Release.

## 6. Как выпускать следующие версии

При следующем обновлении:

1. В `rccars_launcher/ui.py` увеличь `APP_VERSION`, например `0.1.3` → `0.1.4`.
2. Обнови `CHANGELOG.md` и при необходимости `README.md`.
3. Запусти тесты: `py -3 -m pytest -q`.
4. Собери новый EXE на Windows и протестируй его.
5. Создай новый Release с tag `v0.1.4` и прикрепи новый `RCCarsLauncher.exe`.

При проверке лаунчер сравнивает числа в версии тега с `APP_VERSION`. Для предсказуемого сравнения используй теги вида `vMAJOR.MINOR.PATCH`: `v0.1.4`, `v0.2.0`, `v1.0.0`.

## Важные детали

- Не загружай токен GitHub в `launcher_config.json`: для публичного репозитория он не нужен.
- Убедись, что EXE действительно приложен к Release. Один лишь source-code ZIP, автоматически генерируемый GitHub, не подходит для текущего автообновления.
- Если проверка сообщает, что нет `.exe` asset, проверь именно опубликованный **latest stable Release** и точное имя прикреплённого EXE.
- Автообновление заменяет запущенный EXE после его завершения. Рядом с ним сохраняется portable-папка `data`; отдельно поставляемые `launcher_config.json`, `social_links.json` и `Tools` не затираются EXE-обновлением.
- Первую версию лаунчера нужно скачать/установить вручную. Встроенное автообновление начинает работать после того, как настроен репозиторий и опубликован Release с EXE.

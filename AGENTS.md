# Правила для нейронок

## Проект

CQA: прототип оценки качества диалогов операторов для хакатона Freedom Broker. Команда из 4 человек, 24 часа.

Сервер на FastAPI оценивает диалог по настраиваемому чек-листу. Результат: баллы, объяснения и реплики-доказательства. Дальше апелляция, решение проверяющего и пересчёт итога. Интерфейс на HTML, CSS и JS без сборки отдаёт тот же сервер.

Условия хакатона лежат в `docs/BRIEF.md`. PDF в git не попадают, опирайтесь на этот файл.

## Запуск и тесты

Нужен Python 3.13, на нём работает CI.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
uvicorn backend.app.main:create_app --factory --reload
```

Приложение: http://127.0.0.1:8000, документация API: `/docs`.

```powershell
pytest
ruff check .
```

Заглушки работают без ключа модели: `CQA_EVALUATOR=mock`. Настоящая модель пока не подключена: с `CQA_EVALUATOR=llm` приложение не запустится, это задача `llm/evaluator-core`.

## Первый шаг

1. Посмотрите ветку: `git branch --show-current`.
2. Определите роль по префиксу ветки. Нет префикса роли: спросите человека, не начинайте работу.
3. Прочитайте свою задачу в `README.md`, раздел «Задачи и Pull Request».

## Роли и зоны

| Ветка | Кто | Должность | Зона |
|---|---|---|---|
| `backend/*` | atomi7e | Tech Lead / Backend | `backend/`, кроме зон других ролей; `backend/tests/`, кроме `backend/tests/evaluator/`; CI, `requirements.txt`, `pyproject.toml`, `scripts/`, `.gitignore`, `.env.example` и всё, чего нет в других строках |
| `llm/*` | Алдияр (`champaldi`) | AI Engineer | `backend/app/evaluator/`, `backend/tests/evaluator/` |
| `ui/*` | Максим (`Kyjoki`) | Frontend Engineer | `frontend/`, кроме `frontend/checklist/` |
| `qa/*` | Карим (`karim312k1`) | QA / Product Engineer | `backend/app/scoring/`, `backend/tests/`, `frontend/checklist/`, `eval/`, `config/`, `docs/`, `README.md` |
| `contract/*` | Вся команда | | Всё, с согласия всех четверых |

`backend/app/contracts.py`, `frontend/api.js`, `AGENTS.md` и `CLAUDE.md` меняются только в ветке `contract/*`.

## Только своя зона

Правьте файлы только своей роли. Если нужна чужая правка, не делайте её сами: опишите в PR, в разделе «Чужие зоны».

CI проверяет это на каждом PR. Проверить заранее:

```powershell
python scripts/check_scope.py --branch <ваша ветка> --base origin/main
```

Скрипт видит только закоммиченные изменения.

Проверка запускается из кода самого PR, и правка `scripts/` или `.github/` может её отключить. Такие правки проверяющий смотрит руками.

## Как попасть в `main`

Прямой пуш закрыт для всех, включая администратора. Слияние откроется, когда:

1. Зелёные проверки `lint-and-test` и `scope`.
2. Есть одно одобрение от другого участника. Свой PR одобрить нельзя.
3. Ветка обновлена от `main`: кнопка Update branch в PR.

Ревьюера GitHub зовёт сам по `.github/CODEOWNERS`. Слияние только через squash, ветка после него удаляется автоматически.

## Запреты для всех

1. Не зашивать критерии в код. Чек-лист приходит из настроек, новый критерий добавляется без правки кода.
2. Оценивать только оператора. Реплики бота и системы служат контекстом и могут быть доказательством, но сами не оцениваются.
3. Не менять исходную оценку. Апелляции и решения хранятся отдельно, финальный результат считается поверх.
4. Не коммитить секреты и данные. Репозиторий публичный: в git нельзя класть ключи, подписанную ссылку и значения `sig`, идентификаторы диалогов из `data/dev.json`, цитаты из диалогов и находки по данным.
5. Не менять контракт вне `contract/*`.

## Карта кода

| Путь | Что там |
|---|---|
| `backend/app/contracts.py` | Контракт: модели данных для всех ролей |
| `backend/app/settings.py` | Настройки |
| `backend/app/errors.py` | Ошибки |
| `backend/app/services.py` | Сценарии |
| `backend/app/main.py` | Сборка приложения |
| `backend/app/seed.py` | Стартовые данные |
| `backend/app/api/` | Маршруты |
| `backend/app/datasets/` | Загрузка и нормализация диалогов |
| `backend/app/storage/` | Хранилище: Protocol в `base.py`, заглушка `memory.py` |
| `backend/app/evaluator/` | Оценка: Protocol в `base.py`, заглушка `mock.py`, выбор в `factory.py` |
| `backend/app/scoring/engine.py` | Подсчёт баллов (заглушка) |
| `frontend/` | Интерфейс |
| `config/` | Стартовый чек-лист и синтетические примеры диалогов, их читает `seed.py` |
| `scripts/check_scope.py` | Проверка зон |
| `eval/` | Эталон |

## API

Все пути под `/api`. Ответ всегда в конверте `{success, data, error}`, в таблице показано содержимое `data`.

| Запрос | Тело или параметры | Ответ |
|---|---|---|
| `GET /api/health` | | `{status, evaluator, dataset_configured}` |
| `GET /api/dialogs` | `?group_id=` | `DialogSummary[]` |
| `GET /api/dialogs/{id}` | | `Dialog` |
| `POST /api/dialogs/import` | `{group_id}` | `{group_id, imported}` |
| `GET /api/checklists` | | `Checklist[]` |
| `GET /api/checklists/active` | | `Checklist` |
| `GET /api/checklists/{id}` | | `Checklist` |
| `POST /api/checklists` | `ChecklistDraft` | `Checklist` (201, становится активным) |
| `POST /api/evaluations` | `{conversation_id, checklist_id?}` | `EvaluationCard` |
| `GET /api/evaluations/{id}` | | `EvaluationCard` |
| `POST /api/evaluations/{id}/appeals` | `{criterion_id, comment}` | `Appeal` (201) |
| `GET /api/appeals` | `?status=&evaluation_id=` | `Appeal[]` |
| `POST /api/appeals/{id}/decision` | `{action: confirm\|change, reason, answer?, scale_value?}` | `Appeal` |
| `POST /api/batches` | `{group_id, checklist_id?}` | `BatchJob` (202) |
| `GET /api/batches/{id}` | | `BatchJob {status, total, done, failed, errors}` |

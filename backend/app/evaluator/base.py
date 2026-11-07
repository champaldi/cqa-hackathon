"""Интерфейс оценщика. Заглушка и настоящая модель подключаются через него."""

from typing import Protocol

from backend.app.contracts import Checklist, Dialog, EvaluatorOutput


class Evaluator(Protocol):
    def evaluate(self, dialog: Dialog, checklist: Checklist) -> EvaluatorOutput:
        """Оценивает работу оператора. Реплики бота и системы служат только контекстом.

        Возвращает по одному результату на каждый критерий чек-листа. Вызов блокирующий:
        маршруты и пакетная оценка выполняются не в цикле событий.
        """
        ...

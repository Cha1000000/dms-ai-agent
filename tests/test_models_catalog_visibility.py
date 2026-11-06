"""Контракт: недоступный каталог моделей виден, а не подменён чужим.

Проверено живьём на стенде: у ACP-провайдера без авторизации агент не
отдаёт каталог, и UI молча оставался с моделями Claude. Теперь список
пустеет, а рядом с пикером видна причина.
"""
import json
import os
import re

PLUGIN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
I18N = os.path.join(PLUGIN, "i18n.js")
SERVICE = os.path.join(PLUGIN, "AgentService.qml")
CHAT = os.path.join(PLUGIN, "DmsAgentChat.qml")


def test_models_unavailable_string_exists_in_both_languages():
    src = open(I18N, encoding="utf-8").read()
    # Обе секции (en и ru) должны содержать ключ.
    assert src.count('"models.unavailable"') == 2, src.count('"models.unavailable"')
    ru = src.split('"model.best": "Лучшая"', 1)[1]
    assert "models.unavailable" in ru


def test_failed_catalog_clears_the_models_and_records_the_reason():
    src = open(SERVICE, encoding="utf-8").read()
    # Ошибка каталога не должна оставлять чужие модели в пикере: и очистка
    # списка, и причина должны быть в одной ветке обработки ответа.
    branch = re.search(
        r"\}\s*else\s*\{(?P<body>[^}]*models\s*=\s*\[\];[^}]*)\}", src)
    assert branch, "the failed-catalog branch must clear the list"
    assert "modelsError" in branch.group("body"), branch.group("body")
    assert "modelsError" in src
    # И причина должна быть видна пользователю.
    chat = open(CHAT, encoding="utf-8").read()
    assert "modelsError" in chat

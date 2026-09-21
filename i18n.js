.pragma library

// Interface strings. English is the fallback: a key missing from another
// language falls back to it rather than showing the key itself.
//
// Adding a language means adding a table here — nothing else in the plugin
// needs to know about it.
var STRINGS = {
    en: {
        "input.placeholder": "Message...",
        "toolbar.think": "Think",

        "history.empty": "No conversations yet",
        "history.clearAll": "Clear all",

        "confirm.deleteOne": "Delete this conversation?",
        "confirm.deleteAll": "Delete all {n} conversations?",
        "confirm.irreversible": "This cannot be undone.",
        "confirm.cancel": "Cancel",
        "confirm.delete": "Delete",

        "bubble.copyMarkdown": "md",
        "bubble.copyText": "Text",
        "bubble.copied": "copied",

        "model.fast": "Fast",
        "model.balanced": "Balanced",
        "model.best": "Best",

        "status.ready": "Ready",
        "status.thinking": "Thinking...",
        "status.processing": "Processing...",
        "status.writing": "Writing answer...",
        "status.loadingSession": "Loading session...",
        "status.scanningWindows": "Scanning windows...",
        "status.scanningProcesses": "Scanning processes...",
        "status.searchingApps": "Searching apps...",

        "error.micUnavailable": "Microphone unavailable",
        "error.noOutput": "No audio output to capture",
        "error.noSpeech": "No speech recognized",
        "error.noRecognition": "No response from speech recognition",
        "error.noWindow": "Could not capture the focused window",

        // The wording an attachment reaches the agent with.
        "prompt.oneImage": "Look at the image {paths} — this is what is on screen right now.",
        "prompt.manyImages": "Look at the images ({paths}) — this is what is on screen right now."
    },

    ru: {
        "input.placeholder": "Сообщение...",
        "toolbar.think": "Думать",

        "history.empty": "Пока нет разговоров",
        "history.clearAll": "Очистить всё",

        "confirm.deleteOne": "Удалить этот разговор?",
        "confirm.deleteAll": "Удалить все разговоры ({n})?",
        "confirm.irreversible": "Это действие необратимо.",
        "confirm.cancel": "Отмена",
        "confirm.delete": "Удалить",

        "bubble.copyMarkdown": "md",
        "bubble.copyText": "Текст",
        "bubble.copied": "скопировано",

        "model.fast": "Быстрая",
        "model.balanced": "Сбалансированная",
        "model.best": "Лучшая",

        "status.ready": "Готов",
        "status.thinking": "Думаю...",
        "status.processing": "Обрабатываю...",
        "status.writing": "Пишу ответ...",
        "status.loadingSession": "Загружаю сессию...",
        "status.scanningWindows": "Смотрю окна...",
        "status.scanningProcesses": "Смотрю процессы...",
        "status.searchingApps": "Ищу приложения...",

        "error.micUnavailable": "Микрофон недоступен",
        "error.noOutput": "Нечего записывать с вывода",
        "error.noSpeech": "Речь не распознана",
        "error.noRecognition": "Нет ответа от распознавания речи",
        "error.noWindow": "Не удалось снять активное окно",

        "prompt.oneImage": "Посмотри изображение {paths} — это то, что сейчас на экране.",
        "prompt.manyImages": "Посмотри изображения ({paths}) — это то, что сейчас на экране."
    }
};

function t(lang, key, args) {
    var table = STRINGS[lang] || STRINGS.en;
    var text = (key in table) ? table[key] : STRINGS.en[key];
    if (text === undefined) return key;

    if (args) {
        for (var name in args)
            text = text.replace("{" + name + "}", args[name]);
    }
    return text;
}

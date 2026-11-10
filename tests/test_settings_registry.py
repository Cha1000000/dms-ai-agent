import json
import subprocess
from pathlib import Path


SETTINGS = Path(__file__).resolve().parents[1] / "DmsAgentSettings.qml"


def run_script(body):
    source = SETTINGS.read_text()
    names = ("validateEntry", "prepareSave", "confirmNext", "submit", "submitJson",
             "errorFieldFor", "setFieldError", "clearFieldError")
    functions = []
    for name in names:
        start = source.index("        function " + name + "(")
        end = source.index("\n        }", start) + len("\n        }")
        functions.append(source[start:end])
    harness = """
const I18n = {t: (_, key) => key}, root = {uiLanguage: 'en'};
const Providers = {all: () => ['claude', 'cvc', 'cc9', 'qoder', 'kimi'].map(id => ({id}))};
let providers = {}, registryLoaded = true, loadFailed = false, formError = '';
let fieldError = '', fieldErrorField = '';
let pendingId = '', pendingEntry = null, pendingKey = '', pendingCommandText = '', pendingUrlValue = '', pendingNeedsUrl = false;
let saveProc = {running: false}, keyProc = {running: false};
let confirmCommandDialog = {visible: false}, confirmUrlDialog = {visible: false};
let formId = '', pendingEditId = '', formAdapter = '', formTitle = '', formCommand = '', formBaseUrl = '';
let formKeyField = {text: ''}, jsonEntry = {text: ''}, editorId = '', saved = [];
function saveProvider(id, entry) { saved.push({id, entry, key: pendingKey}); }
""" + "\n".join(functions) + "\n" + body
    result = subprocess.run(["node", "-e", harness], capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def test_new_command_requires_confirmation_and_preserves_form_and_key():
    result = run_script("""
formId = 'example'; formAdapter = 'acp'; formTitle = 'Example';
formCommand = 'agent --flag'; formKeyField.text = 'test-key';
submit();
let before = {dialog: confirmCommandDialog.visible, saved: saved.length, command: pendingCommandText};
confirmNext();
console.log(JSON.stringify({before, saved}));
""")
    assert result["before"] == {"dialog": True, "saved": 0, "command": '[\n  "agent",\n  "--flag"\n]'}
    assert result["saved"] == [{"id": "example", "entry": {"adapter": "acp", "title": "Example", "command": ["agent", "--flag"]}, "key": "test-key"}]


def test_json_command_and_url_confirmations_preserve_entry():
    result = run_script("""
providers.x = {adapter:'openai', title:'Old', baseUrl:'https://old.example/v1'};
editorId = 'x'; jsonEntry.text = JSON.stringify({adapter:'openai',title:'New',baseUrl:'https://new.example/v1'});
submitJson(); let url = {dialog:confirmUrlDialog.visible, saved:saved.length};
confirmNext();
providers.y = {adapter:'acp',title:'Old',command:['old']}; editorId = 'y';
jsonEntry.text = JSON.stringify({adapter:'acp',title:'New',command:['new','arg with space']});
submitJson(); let cmd = {dialog:confirmCommandDialog.visible, saved:saved.length};
confirmNext(); console.log(JSON.stringify({url,cmd,saved}));
""")
    assert result["url"] == {"dialog": True, "saved": 0}
    assert result["cmd"] == {"dialog": True, "saved": 1}
    assert result["saved"][0]["entry"] == {"adapter": "openai", "title": "New", "baseUrl": "https://new.example/v1"}
    assert result["saved"][1]["entry"] == {"adapter": "acp", "title": "New", "command": ["new", "arg with space"]}


def test_json_rejects_secret_fields_unsafe_urls_and_unknown_adapter():
    result = run_script("""
let cases = [
  {adapter:'acp',command:['tool'],keys:{apiKey:'secret'}},
  {adapter:'openai',baseUrl:'https://user:secret@example.org/v1'},
  {adapter:'openai',baseUrl:'http://example.org/v1'},
  {adapter:'unknown',command:['tool']},
  {adapter:'acp',command:['tool',4]},
];
console.log(JSON.stringify(cases.map(x => validateEntry('example', x))));
""")
    assert result == ["settings.reg.badFields", "settings.reg.badUrl", "settings.reg.badUrl", "settings.reg.badAdapter", "settings.reg.needCommand"]


def test_builtin_provider_ids_cannot_be_added():
    result = run_script("""
console.log(JSON.stringify([
  validateEntry('claude', {adapter:'acp',command:['tool']}),
  validateEntry('cvc', {adapter:'openai',baseUrl:'https://x.example/v1'}),
  validateEntry('my-gw', {adapter:'openai',baseUrl:'https://x.example/v1'}),
]));
""")
    assert result == ["settings.reg.reservedId", "settings.reg.reservedId", ""]

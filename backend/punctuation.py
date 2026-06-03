"""Chinese punctuation restoration using FunASR punc_ct-transformer (local model).
Falls back to legacy HuggingFace model if FunASR unavailable."""
from pathlib import Path
import torch

MODEL_DIR = Path(__file__).parent.parent / "model" / "punctuation_funasr"
LEGACY_DIR = Path(__file__).parent.parent / "model" / "punctuation"

_model = None


def _ensure_loaded():
    global _model
    if _model is not None:
        return
    if MODEL_DIR.is_dir():
        from funasr import AutoModel
        _model = AutoModel(
            model=str(MODEL_DIR),
            model_revision="v2.0.4",
            disable_pbar=True,
            device="cuda:0" if torch.cuda.is_available() else "cpu",
        )
    elif LEGACY_DIR.is_dir():
        from transformers import AutoTokenizer, AutoModelForTokenClassification
        _tokenizer = AutoTokenizer.from_pretrained(str(LEGACY_DIR))
        _model = AutoModelForTokenClassification.from_pretrained(str(LEGACY_DIR))
        if torch.cuda.is_available():
            _model = _model.to("cuda")
        _model._tokenizer = _tokenizer
        _model._is_legacy = True
    else:
        raise FileNotFoundError(
            f"标点模型未找到。请下载到 {MODEL_DIR}/ 或 {LEGACY_DIR}/")


def restore_punctuation(text: str) -> str:
    text = text.strip()
    if not text:
        return text
    _ensure_loaded()

    if hasattr(_model, '_is_legacy'):
        # Legacy HuggingFace model path
        return _legacy_restore(text)
    else:
        # FunASR model path
        result = _model.generate(input=text)
        if result and len(result) > 0:
            return result[0].get("text", text)
        return text


def _legacy_restore(text: str) -> str:
    """Legacy punctuation restoration using HuggingFace model."""
    enc = _model._tokenizer(text, return_tensors="pt", truncation=True, max_length=512)
    if torch.cuda.is_available():
        enc = enc.to("cuda")
    with torch.no_grad():
        outputs = _model(**enc)
        predictions = torch.argmax(outputs.logits, dim=-1)[0]
    input_ids = enc["input_ids"][0].tolist()
    result = []
    SKIP_IDS = {0, 1, 2, 3}
    PUNCT_MAP = {"0": "", ".": "。", ",": "，", "?": "？", "-": "", ":": "："}
    for tid, pred_id in zip(input_ids, predictions):
        if tid in SKIP_IDS:
            continue
        token_text = _model._tokenizer.decode([tid])
        if not token_text.strip():
            continue
        label = _model.config.id2label.get(pred_id.item(), "0")
        punct = PUNCT_MAP.get(label, "")
        result.append(token_text + punct)
    return "".join(result).strip()

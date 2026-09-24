import tempfile
import unittest
from pathlib import Path

try:
    import peft  # noqa: F401
    import torch  # noqa: F401
    import transformers  # noqa: F401
    HAS_DEPS = True
except ImportError:
    HAS_DEPS = False

CHATML = ("{% for m in messages %}<|im_start|>{{ m['role'] }}\n{{ m['content'] }}<|im_end|>\n{% endfor %}"
          "{% if add_generation_prompt %}<|im_start|>assistant\n{% endif %}")


def make_tiny_qwen(path: Path) -> None:
    """Apró, véletlen súlyú Qwen3 felépítésű modell – a valódi alapmodell helyett a teszthez."""
    from tokenizers import Tokenizer, decoders, models, pre_tokenizers, trainers
    from transformers import PreTrainedTokenizerFast, Qwen3Config, Qwen3ForCausalLM
    raw = Tokenizer(models.BPE())
    raw.pre_tokenizer = pre_tokenizers.ByteLevel(add_prefix_space=False)
    raw.decoder = decoders.ByteLevel()
    raw.train_from_iterator(["A VLAN a hálózat logikai felosztása. Szia, segítek!"] * 50,
                            trainers.BpeTrainer(vocab_size=400, special_tokens=["<|im_start|>", "<|im_end|>"],
                                                initial_alphabet=pre_tokenizers.ByteLevel.alphabet()))
    tok = PreTrainedTokenizerFast(tokenizer_object=raw, eos_token="<|im_end|>", pad_token="<|im_end|>")
    tok.chat_template = CHATML
    tok.save_pretrained(path)
    cfg = Qwen3Config(vocab_size=tok.vocab_size, hidden_size=32, intermediate_size=64, num_hidden_layers=2,
                      num_attention_heads=2, num_key_value_heads=1, head_dim=16, max_position_embeddings=256,
                      eos_token_id=tok.eos_token_id, pad_token_id=tok.pad_token_id)
    Qwen3ForCausalLM(cfg).save_pretrained(path)


@unittest.skipUnless(HAS_DEPS, "torch/transformers/peft nincs telepítve")
class BaseModelTest(unittest.TestCase):
    def test_finetune_resume_and_use(self):
        from tecf.config import Config
        from tecf.knowledge import KnowledgeBase
        from tecf.llm import pipeline
        from tecf.llm.base import BaseModelRunner, finetune, paths
        from tecf.providers import get_provider

        with tempfile.TemporaryDirectory() as d:
            base = Path(d) / "tiny-qwen"
            make_tiny_qwen(base)
            cfg = Config.load(d)
            kb = KnowledgeBase(cfg.db_path)
            for i in range(12):
                kb.add_document(f"{i}. A VLAN a hálózat logikai felosztása, trunk porton több VLAN megy. " * 8,
                                f"doc{i}", trust=0.9)
            kb.remember("A DC01 a tartományvezérlő.")
            cid = kb.log_conversation("Mi a VLAN?", "A VLAN virtuális helyi hálózat.", "t", 1)
            kb.rate(cid, 1)
            kb.close()

            logs: list[str] = []
            info1 = finetune(cfg, minutes=0.15, base=str(base), max_len=128, log=logs.append)
            p = paths(cfg)
            self.assertTrue((p["model"] / "config.json").exists())
            self.assertTrue((p["adapter"] / "adapter_config.json").exists())
            info2 = finetune(cfg, minutes=0.15, log=logs.append)  # folytatás, az alap az info.json-ból
            self.assertTrue(any("Folytatás" in m for m in logs))
            self.assertEqual(info2["base"], str(base))
            self.assertGreater(info2["steps"], info1["steps"])
            self.assertLessEqual(info2["val_loss"], info1["val_loss"])

            self.assertIsInstance(BaseModelRunner.get(p["model"]).chat(
                [{"role": "user", "content": "Mi a VLAN?"}], max_tokens=10), str)
            pipeline.use(cfg, True)
            prov = get_provider("tecf-sajat", {})
            prov.base_url = str(Path(d) / "sajat_modell")
            self.assertTrue(prov.available())
            self.assertIsInstance(prov.chat([{"role": "user", "content": "Szia"}], max_tokens=10), str)


if __name__ == "__main__":
    unittest.main()

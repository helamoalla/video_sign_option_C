from pathlib import Path
import shutil
import re
import json

from app.avatar.base import AvatarProvider
from app.gloss_dictionary import get_sigml_dir, normalize_language


ALIASES_PATH = Path("data/sign_languages/gloss_aliases.json")


class CwasaMultilangProvider(AvatarProvider):
    def __init__(self):
        self.project_root = Path("external/alsl_avatar")
        self.web_simulator = self.project_root / "web-simulator"

    def normalize_word(self, word, language="lsa"):
        lang = normalize_language(language)
        word = str(word).strip()

        if lang == "lsa":
            word = re.sub(r"[\u064b-\u065f\u0670]", "", word)
            word = (
                word.replace("أ", "ا")
                .replace("إ", "ا")
                .replace("آ", "ا")
                .replace("ة", "ه")
                .replace("ى", "ي")
            )
            return re.sub(r"[^\u0600-\u06FF0-9]", "", word).strip()

        return re.sub(r"[^A-Za-zÀ-ÿ0-9_-]", "", word).strip().upper()

    def decode_unicode_sigml_name(self, name: str) -> str:
        if "#U" not in name:
            return name

        chars = []
        for part in name.split("#U"):
            if not part:
                continue
            try:
                chars.append(chr(int(part[:4], 16)))
            except ValueError:
                continue

        return "".join(chars)

    def load_aliases(self, language):
        if not ALIASES_PATH.exists():
            return {}

        try:
            data = json.loads(ALIASES_PATH.read_text(encoding="utf-8"))
            return data.get(normalize_language(language), {})
        except Exception:
            return {}

    def find_sigml_file(self, word, language):
        aliases = self.load_aliases(language)

        candidates = [
            word,
            aliases.get(word, word),
            self.normalize_word(word, language),
        ]

        normalized = {
            self.normalize_word(c, language)
            for c in candidates
            if c
        }

        for path in get_sigml_dir(language).rglob("*.sigml"):
            decoded_stem = self.decode_unicode_sigml_name(path.stem)

            file_variants = {
                decoded_stem,
                path.stem,
            }

            for sep in ["_", "-", " "]:
                if sep in decoded_stem:
                    file_variants.update(decoded_stem.split(sep))

            if "_" in decoded_stem:
                file_variants.add(decoded_stem.split("_")[0])
                file_variants.add(decoded_stem.split("_")[-1])

            normalized_variants = {
                self.normalize_word(v, language)
                for v in file_variants
                if v
            }

            if normalized.intersection(normalized_variants):
                return path

            for n in normalized:
                for fv in normalized_variants:
                    if len(n) > 3 and len(fv) > 3 and (n in fv or fv in n):
                        return path

        return None

    def generate(
        self,
        text: str,
        language: str,
        output_path: str,
        glosses: list[str] | None = None,
    ):
        output_dir = Path(output_path).with_suffix("")
        output_dir.mkdir(parents=True, exist_ok=True)

        if not self.web_simulator.exists():
            raise FileNotFoundError("external/alsl_avatar/web-simulator not found")

        for item in self.web_simulator.iterdir():
            if item.name == "sigml":
                continue

            dest = output_dir / item.name
            if item.is_dir():
                shutil.copytree(item, dest, dirs_exist_ok=True)
            else:
                shutil.copy2(item, dest)
        
                # The repository stores shaders at:
        # web-simulator/shaders/
        #
        # CWASA resolves them relative to allcsa.js and requests:
        # web-simulator/cwa/shaders/
        source_shaders_dir = (
            self.web_simulator
            / "shaders"
        )

        runtime_shaders_dir = (
            output_dir
            / "cwa"
            / "shaders"
        )

        if not source_shaders_dir.is_dir():
            raise FileNotFoundError(
                "CWASA shaders directory was not found: "
                f"{source_shaders_dir}"
            )

        shutil.copytree(
            source_shaders_dir,
            runtime_shaders_dir,
            dirs_exist_ok=True,
        )

        required_shaders = [
            runtime_shaders_dir / "qskin.vert",
            runtime_shaders_dir / "qskin.frag",
        ]

        for shader_path in required_shaders:
            if (
                not shader_path.is_file()
                or shader_path.stat().st_size == 0
            ):
                raise RuntimeError(
                    "Required CWASA shader is missing "
                    f"or empty: {shader_path}"
                )


        # Older simulator layouts store h2s.xsl beside index.html,
        # but this CWASA build may request it from cwa/h2s.xsl.
        source_h2s_path = (
            self.web_simulator
            / "h2s.xsl"
        )

        runtime_h2s_path = (
            output_dir
            / "cwa"
            / "h2s.xsl"
        )

        if source_h2s_path.is_file():
            shutil.copy2(
                source_h2s_path,
                runtime_h2s_path,
            )
            
        categories_file = (
            output_dir
            / "categories_files.json"
        )

        categories_file.write_text(
            "{}",
            encoding="utf-8",
        )

        sigml_dir = output_dir / "sigml"
        sigml_dir.mkdir(parents=True, exist_ok=True)

        if glosses is not None:
            words = [
                str(gloss).strip()
                for gloss in glosses
                if str(gloss).strip()
            ]
        else:
            # Used only by direct/test calls that do not provide
            # an already generated sign plan.
            words = [
                self.normalize_word(word, language)
                for word in text.split()
                if self.normalize_word(
                    word,
                    language,
                )
            ]

        if not words:
            raise ValueError(
                "No validated glosses were provided "
                "for avatar generation."
            )

        found = []
        missing = []

        for word in words:
            f = self.find_sigml_file(word, language)

            if f:
                safe = self.normalize_word(word, language) or self.decode_unicode_sigml_name(f.stem)
                shutil.copy(f, sigml_dir / f"{safe}.sigml")
                found.append(safe)
            else:
                missing.append(word)

        if not found:
            raise ValueError(
                f"No SiGML assets found for language={language}. "
                f"Add files under {get_sigml_dir(language)}. Missing: {missing}"
            )

        gloss_text = " ".join(found)

        index_path = (
            output_dir / "index.html"
        )

        html = index_path.read_text(
            encoding="utf-8"
        )

        # Use JSON encoding instead of placing values directly inside
        # JavaScript string literals.
        language_json = json.dumps(
            language,
            ensure_ascii=False,
        )

        gloss_text_json = json.dumps(
            gloss_text,
            ensure_ascii=False,
        )

        found_json = json.dumps(
            found,
            ensure_ascii=False,
        )

        missing_json = json.dumps(
            missing,
            ensure_ascii=False,
        )

        injection = f"""
        <script>
        window.CYRKIL_SIGN_LANGUAGE = {language_json};
        window.CYRKIL_FOUND_GLOSSES = {found_json};
        window.CYRKIL_MISSING_GLOSSES = {missing_json};
        window.CYRKIL_SIGN_PLAN_READY = false;

        window.addEventListener("load", function() {{
            setTimeout(function() {{
                var input = document.getElementById(
                    "glossInput"
                );

                if (input) {{
                    input.value = {gloss_text_json};
                    window.CYRKIL_SIGN_PLAN_READY = true;
                }}
            }}, 2000);
        }});
        </script>
        """

        html = html.replace(
            "</body>",
            injection + "\n</body>",
        )

        index_path.write_text(
            html,
            encoding="utf-8",
        )

        return str(index_path)
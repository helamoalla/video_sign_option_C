import json
from pathlib import Path


def build_player(
    session_dir: Path,
    video_url: str,
    subtitles: dict,
    avatars: dict,
):
    """
    Generate the browser player for a completed video job.

    video_url, subtitles and avatars remain in the function
    signature for compatibility with existing pipeline calls.
    """

    session_name_json = json.dumps(
        session_dir.name
    )

    html = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta
  name="viewport"
  content="width=device-width, initial-scale=1"
/>
<meta
  name="referrer"
  content="no-referrer"
/>

<title>CYRKIL Geo-Adaptive Sign Player</title>

<style>
body {
  background: #111;
  color: white;
  font-family: Arial, sans-serif;
  text-align: center;
  margin: 0;
  padding: 20px;
}

.panel {
  width: 900px;
  max-width: 95vw;
  margin: 15px auto;
  background: #1b1b1b;
  padding: 15px;
  border-radius: 12px;
}

.row {
  display: flex;
  justify-content: center;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  margin: 10px 0;
}

select,
button {
  padding: 11px 16px;
  border: 0;
  border-radius: 8px;
  cursor: pointer;
  font-size: 15px;
}

button {
  background: #333;
  color: white;
}

button.active {
  background: #4caf50;
}

button:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.lsa {
  background: #d9362b;
  font-weight: bold;
}

video {
  width: 900px;
  max-width: 95vw;
  border-radius: 14px;
  background: #222;
  margin-top: 15px;
}

.status {
  color: #ddd;
  font-size: 14px;
  margin-top: 8px;
}

.status.error {
  color: #ff7777;
}

.debug {
  width: 900px;
  max-width: 95vw;
  margin: 15px auto;
  text-align: left;
  background: #1b1b1b;
  padding: 12px;
  border-radius: 8px;
  color: #ccc;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  font-size: 13px;
}
</style>
</head>

<body>

<h2>CYRKIL Geo-Adaptive Sign Player</h2>

<p>
  Détection automatique, sélection manuelle
  et LSA toujours disponible
</p>

<div class="panel">
  <div class="row">
    <label for="countrySelect">
      🌍 Pays utilisateur :
    </label>

    <select id="countrySelect"></select>
  </div>

  <div class="row">
    <button
      id="autoDetectBtn"
      type="button"
    >
      📍 Détecter via navigateur
    </button>

    <button
      id="lsaBtn"
      class="lsa"
      type="button"
    >
      🌍 LSA toujours disponible
    </button>
  </div>

  <div
    class="row"
    id="languageButtons"
  ></div>

  <div
    class="status"
    id="status"
  >
    Chargement du lecteur…
  </div>
</div>

<video
  id="mainVideo"
  controls
  playsinline
  preload="metadata"
></video>

<div
  class="debug"
  id="debug"
></div>

<script>
const sessionName = __SESSION_NAME_JSON__;

const playbackToken = new URLSearchParams(
  window.location.search
).get("token");

let manifest = null;

const video = document.getElementById(
  "mainVideo"
);

const countrySelect = document.getElementById(
  "countrySelect"
);

const languageButtons = document.getElementById(
  "languageButtons"
);

const debug = document.getElementById(
  "debug"
);

const statusBox = document.getElementById(
  "status"
);

const autoDetectBtn = document.getElementById(
  "autoDetectBtn"
);

const lsaBtn = document.getElementById(
  "lsaBtn"
);

const COUNTRIES = [
  {
    code: "FR",
    label: "🇫🇷 France",
    sign: "LSF"
  },
  {
    code: "DE",
    label: "🇩🇪 Germany",
    sign: "DGS"
  },
  {
    code: "GB",
    label: "🇬🇧 United Kingdom",
    sign: "BSL"
  },
  {
    code: "GR",
    label: "🇬🇷 Greece",
    sign: "GSL"
  },
  {
    code: "IT",
    label: "🇮🇹 Italy",
    sign: "LIS"
  },
  {
    code: "ES",
    label: "🇪🇸 Spain",
    sign: "LSE"
  },
  {
    code: "NL",
    label: "🇳🇱 Netherlands",
    sign: "NGT"
  },
  {
    code: "PL",
    label: "🇵🇱 Poland",
    sign: "PJM"
  }
];


function setError(message) {
  statusBox.classList.add("error");
  statusBox.innerText = message;
}


function clearError() {
  statusBox.classList.remove("error");
}


function addPlaybackToken(path) {
  if (!path) {
    return null;
  }

  const url = new URL(
    path,
    window.location.href
  );

  if (playbackToken) {
    url.searchParams.set(
      "token",
      playbackToken
    );
  }

  return url.toString();
}


function makeLocalPath(path) {
  if (!path) {
    return null;
  }

  let resolvedPath = path;

  const marker = (
    "/outputs/"
    + sessionName
    + "/"
  );

  if (path.includes(marker)) {
    resolvedPath = path.split(
      marker
    )[1];

  } else if (
    path.startsWith("/outputs/")
  ) {
    const parts = path.split("/");
    const sessionIndex = parts.indexOf(
      sessionName
    );

    if (sessionIndex !== -1) {
      resolvedPath = parts
        .slice(sessionIndex + 1)
        .join("/");
    }

  } else if (
    path.startsWith("/")
  ) {
    resolvedPath = (
      window.location.origin
      + path
    );
  }

  return addPlaybackToken(
    resolvedPath
  );
}


function getVideoKeys() {
  return Object.keys(
    manifest?.rendered_videos || {}
  );
}


function findKeyBySign(sign) {
  const normalizedSign = (
    sign || ""
  ).toUpperCase();

  const keys = getVideoKeys();

  const exact = keys.find(
    key => (
      key.toUpperCase()
      === normalizedSign
    )
  );

  if (exact) {
    return exact;
  }

  return keys.find(
    key => (
      key.toUpperCase().endsWith(
        "_" + normalizedSign
      )
    )
  ) || null;
}


function resolveVideoKey(sign) {
  const requestedKey = findKeyBySign(
    sign
  );

  if (requestedKey) {
    return {
      key: requestedKey,
      fallback: false
    };
  }

  const lsaKey = findKeyBySign(
    "LSA"
  );

  if (lsaKey) {
    return {
      key: lsaKey,
      fallback: true
    };
  }

  const lsfKey = findKeyBySign(
    "LSF"
  );

  if (lsfKey) {
    return {
      key: lsfKey,
      fallback: true
    };
  }

  return {
    key: getVideoKeys()[0] || null,
    fallback: true
  };
}


function setActiveLanguage(sign) {
  const normalizedSign = (
    sign || ""
  ).toUpperCase();

  document
    .querySelectorAll(
      "#languageButtons button"
    )
    .forEach(button => {
      button.classList.toggle(
        "active",
        button.dataset.sign
          === normalizedSign
      );
    });

  lsaBtn.classList.toggle(
    "active",
    normalizedSign === "LSA"
  );
}


function loadVideoBySign(
  sign,
  source
) {
  clearError();

  const resolved = resolveVideoKey(
    sign
  );

  const key = resolved.key;

  if (!key) {
    setError(
      "Aucune vidéo disponible."
    );

    return;
  }

  const rawPath = (
    manifest.rendered_videos[key]
  );

  const videoPath = makeLocalPath(
    rawPath
  );

  if (!videoPath) {
    setError(
      "Le chemin de la vidéo est invalide."
    );

    return;
  }

  video.src = videoPath;
  video.load();

  setActiveLanguage(sign);

  let message = (
    "Source: "
    + source
    + " | Langue demandée: "
    + sign.toUpperCase()
    + " | Vidéo chargée: "
    + key
  );

  if (resolved.fallback) {
    message += " | Fallback utilisé";
  }

  statusBox.innerText = message;

  debug.innerText = (
    "Selected video: "
    + key
    + "\\n"
    + "Requested sign language: "
    + sign
    + "\\n"
    + "Source: "
    + source
    + "\\n"
    + "Video path: "
    + videoPath
    + "\\n\\n"
    + "Original text:\\n"
    + (manifest.original_text || "")
    + "\\n\\n"
    + "Translations:\\n"
    + JSON.stringify(
      manifest.translations || {},
      null,
      2
    )
    + "\\n\\n"
    + "Glosses:\\n"
    + JSON.stringify(
      manifest.avatar_debug || {},
      null,
      2
    )
  );
}


function routeByCountry(
  countryCode
) {
  const country = COUNTRIES.find(
    item => item.code === countryCode
  );

  if (!country) {
    loadVideoBySign(
      "LSA",
      "fallback_country_unknown"
    );

    return;
  }

  loadVideoBySign(
    country.sign,
    "manual_country_" + countryCode
  );
}


function detectFromBrowserLanguage() {
  const language = (
    navigator.language || ""
  ).toLowerCase();

  if (language.startsWith("fr")) {
    countrySelect.value = "FR";
    routeByCountry("FR");

  } else if (
    language.startsWith("de")
  ) {
    countrySelect.value = "DE";
    routeByCountry("DE");

  } else if (
    language.startsWith("en")
  ) {
    countrySelect.value = "GB";
    routeByCountry("GB");

  } else if (
    language.startsWith("el")
  ) {
    countrySelect.value = "GR";
    routeByCountry("GR");

  } else if (
    language.startsWith("ar")
  ) {
    loadVideoBySign(
      "LSA",
      "browser_language_arabic"
    );

  } else {
    countrySelect.value = "FR";
    routeByCountry("FR");
  }
}


function buildCountrySelector() {
  countrySelect.innerHTML = "";

  COUNTRIES.forEach(country => {
    const option = document.createElement(
      "option"
    );

    option.value = country.code;

    option.textContent = (
      country.label
      + " → "
      + country.sign
    );

    countrySelect.appendChild(
      option
    );
  });

  countrySelect.onchange = () => {
    routeByCountry(
      countrySelect.value
    );
  };
}


function buildLanguageButtons() {
  languageButtons.innerHTML = "";

  const signs = [
    "LSF",
    "DGS",
    "BSL",
    "GSL"
  ];

  signs.forEach(sign => {
    const key = findKeyBySign(
      sign
    );

    if (!key) {
      return;
    }

    const button = document.createElement(
      "button"
    );

    button.type = "button";
    button.innerText = key;
    button.dataset.sign = sign;

    button.onclick = () => {
      loadVideoBySign(
        sign,
        "manual_sign_language"
      );
    };

    languageButtons.appendChild(
      button
    );
  });

  const lsaAvailable = Boolean(
    findKeyBySign("LSA")
  );

  lsaBtn.disabled = !lsaAvailable;
  lsaBtn.dataset.sign = "LSA";

  lsaBtn.onclick = () => {
    loadVideoBySign(
      "LSA",
      "manual_lsa_button"
    );
  };

  autoDetectBtn.onclick = (
    detectFromBrowserLanguage
  );
}


async function init() {
  try {
    if (!playbackToken) {
      throw new Error(
        "Playback token missing."
      );
    }

    const manifestUrl = (
      addPlaybackToken(
        "manifest.json"
      )
    );

    const response = await fetch(
      manifestUrl,
      {
        method: "GET",
        credentials: "omit",
        referrerPolicy: "no-referrer"
      }
    );

    if (!response.ok) {
      throw new Error(
        "Manifest request failed: "
        + response.status
      );
    }

    manifest = await response.json();

    if (
      !manifest
      || !manifest.rendered_videos
    ) {
      throw new Error(
        "Manifest contains no rendered videos."
      );
    }

    buildCountrySelector();
    buildLanguageButtons();
    detectFromBrowserLanguage();

  } catch (error) {
    setError(
      "Impossible de charger le lecteur. "
      + "Le lien est peut-être expiré."
    );

    debug.innerText = String(
      error
    );
  }
}


video.addEventListener(
  "error",
  () => {
    setError(
      "Impossible de charger cette vidéo. "
      + "Le lien est peut-être expiré."
    );
  }
);


init();
</script>

</body>
</html>
"""

    html = html.replace(
        "__SESSION_NAME_JSON__",
        session_name_json,
    )

    player_path = (
        session_dir / "player.html"
    )

    player_path.write_text(
        html,
        encoding="utf-8",
    )

    return player_path
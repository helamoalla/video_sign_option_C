# Third-Party Notices

This project includes or depends on third-party software, fonts,
sign-language resources and avatar-rendering components.

The licence of the main application does not replace or override the
licences of these third-party components.

## Production asset policy

The current CWASA renderer and ALSL/Dicta-Sign SiGML resources are used
only for research, local development and prototype demonstrations.

They are not approved for Cyrkil production use because commercial-use
and redistribution rights have not been confirmed for every component.

Production avatar generation will use only avatar/sign-language videos
generated, owned or commercially licensed by Cyrkil.

---

## IBM Plex Sans Arabic

- Component: IBM Plex Sans Arabic
- File:
  `app/assets/fonts/IBMPlexSansArabic-SemiBold.ttf`
- Copyright: IBM Corporation
- Source: https://github.com/IBM/plex
- Licence: SIL Open Font License 1.1
- Use: Arabic subtitle rendering
- Redistribution status: Permitted under SIL OFL 1.1
- Commercial use: Permitted under SIL OFL 1.1
- Licence file: `licenses/IBM-Plex-OFL-1.1.txt`

The font licence must remain distributed with the bundled font file.

---

## Noto Fonts

- Component: Noto font family
- Source: https://github.com/notofonts
- Copyright: Google LLC and the respective font authors
- Licence: SIL Open Font License 1.1
- Use: System fallback and subtitle text rendering
- Installation: Installed as a Debian package in the Docker image
- Commercial use: Permitted under the applicable SIL OFL
- Redistribution status: Subject to the applicable package and font
  licence notices

---

## Algerian Sign Language 3D Avatar

- Component: Algerian Sign Language 3D Avatar project
- Location: `external/alsl_avatar/`
- Authors: Amine Mami, Mohamed Elfares Slimani and contributors
- Use: Prototype LSA SiGML assets and CWASA avatar integration
- Licence status: Requires clarification

The upstream project contains conflicting licence information:

- Its README declares CC BY-NC 4.0.
- Its included `LICENSE` file contains GPLv3.

The licence scope over source code, SiGML data, avatar models and
generated media has not been confirmed.

Therefore:

- Production use: Not approved
- Commercial use: Not approved
- Commercial redistribution: Not approved
- Prototype development: Permitted only in an explicitly configured
  non-production environment
- Required action: Obtain written licence clarification or replace the
  assets with Cyrkil-owned or commercially licensed assets

---

## Dicta-Sign Lexicon

- Component: Dicta-Sign basic lexicon and derived SiGML resources
- Languages: LSF, DGS, BSL and GSL
- Source:
  https://www.sign-lang.uni-hamburg.de/dicta-sign/portal/
- Use: Prototype sign-language gloss and SiGML assets
- Licence status: Research licence / requires confirmation

Relevant locations include:

- `external/alsl_avatar/data/sigml/lsf/`
- `external/alsl_avatar/data/sigml/dgs/`
- `external/alsl_avatar/data/sigml/BSL/`
- `external/alsl_avatar/data/sigml/GSL/`

Some Arabic/LSA prototype resources may also have been derived from or
renamed from Dicta-Sign French resources.

Therefore:

- Production use: Not approved
- Commercial use: Not approved
- Redistribution status: Not confirmed
- Required action: Obtain written permission or exclude these assets
  from production distribution

Renaming, translating or converting an asset does not remove the
original licence requirements.

---

## CWASA / JASigning

- Component: CWASA/JASigning web simulator
- Locations:
  - `external/alsl_avatar/web-simulator/cwa/`
  - `external/alsl_avatar/web-simulator/avatars/`
  - Related JavaScript, JAR, shader, configuration and XSL files
- Sources:
  - https://vh.cmp.uea.ac.uk/index.php/CWA_Signing_Avatars
  - https://vh.cmp.uea.ac.uk/index.php/SiGML
- Use: Prototype rendering of SiGML through a 3D signing avatar
- Licence status: Requires confirmation

Therefore:

- Production use: Not approved
- Commercial use: Not approved
- Redistribution status: Not confirmed
- Required action: Obtain the applicable licence or replace the
  renderer and assets

The application blocks CWASA providers in production through
`app/avatar/license_policy.py`.

---

## FFmpeg

- Component: FFmpeg
- Source: https://ffmpeg.org/
- Use:
  - Media probing
  - Media validation
  - Metadata sanitisation
  - Encoding
  - Subtitle and avatar composition
- Installation: Installed as a Debian system package in the Docker image
- Licence: Depends on the exact FFmpeg build configuration; commonly
  LGPL with GPL obligations when GPL components are enabled
- Required action: Preserve the Debian/FFmpeg licence notices and record
  the exact production package version and build configuration

---

## Playwright and Chromium

- Components: Playwright and Chromium
- Use: Recording prototype CWASA avatar output
- Installation: Installed during the Docker image build
- Licence status: Subject to their respective upstream licences and
  bundled third-party notices
- Required action: Preserve notices included in the installed packages

The production Cyrkil video provider is expected to remove the runtime
dependency on Playwright/CWASA recording where it is no longer needed.

---

## Cyrkil production avatar assets

The planned production avatar provider will use videos generated,
recorded, owned or commercially licensed by Cyrkil.

Each production asset must include:

- A unique asset identifier
- The source or owner
- The applicable licence
- Licence or contract evidence
- Commercial-use approval
- Server-side processing approval
- Generated-output rights
- Sign-language validation information
- Performer or model release where applicable

Production assets will be validated using `app/asset_license.py` before
they are accepted or processed.

---

## User-uploaded media

Uploaded videos, audio, subtitles and generated outputs are not
third-party assets distributed as part of this source repository.

Users must confirm that they have the right to upload and process their
media. Generated outputs remain subject to the rights applicable to
their source media and approved production avatar assets.

---

## Environment restrictions

Prototype assets may be enabled only with an explicit development
configuration:

```env
APP_ENV=development
ALLOW_RESEARCH_ASSETS=true

Production must disable prototype assets:

```env
APP_ENV=production
ALLOW_RESEARCH_ASSETS=false
```

In production, CWASA, ALSL and Dicta-Sign resources must not be used unless Cyrkil obtains the appropriate commercial licences. The planned production replacement is Cyrkil-owned or commercially licensed avatar videos.
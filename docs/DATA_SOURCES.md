# Data Sources and Production Asset Policy

## Production decision

The current CWASA avatar renderer and the SiGML resources derived from
ALSL and Dicta-Sign are used only for research, development and
prototype demonstration.

They are not approved for Cyrkil production use because commercial-use
and redistribution rights have not been confirmed for every component.

## Planned production replacement

CWASA avatar generation will be replaced by avatar/sign-language videos
generated, owned or commercially licensed by Cyrkil.

The production provider will use only assets that have:

- Confirmed commercial-use rights.
- Confirmed server-side processing rights.
- Confirmed rights for generated video outputs.
- Source and ownership documentation.
- Sign-language validation.
- Performer/model releases where applicable.

The application provider interface is intentionally separated from the
processing pipeline so the prototype CWASA provider can later be
replaced without rewriting transcription, translation, subtitles,
authentication, queues, storage or media retention.

## Prototype-only components

### Dicta-Sign

Used by the prototype SiGML directories for LSF, DGS, BSL and GSL.

Commercial production: prohibited until written permission is obtained.

### Algerian Sign Language avatar project

Used by the prototype LSA and CWASA integration.

The upstream repository contains conflicting CC BY-NC 4.0 and GPLv3
statements. Commercial production is prohibited until the applicable
licence scope is clarified.

### CWASA / JASigning

Used by the prototype 3D avatar renderer.

Commercial production and redistribution are prohibited until the
applicable licence is confirmed.

## Approved components

### IBM Plex Sans Arabic

Used for Arabic subtitle rendering.

Licence: SIL Open Font License 1.1.

## Environment policy

Development may enable prototype assets explicitly:

APP_ENV=development
ALLOW_RESEARCH_ASSETS=true

Production must use:

APP_ENV=production
ALLOW_RESEARCH_ASSETS=false

The application must reject a prototype provider in production.
# Weather library

Four analyses (UTCI, thermal comfort statistics, pedestrian wind comfort and solar radiation) need hourly weather. Microclimate Studio keeps a
small, documented library of EPW files so that every run says exactly which weather it used and where that weather
came from.

## The decision the library serves

Choosing a weather file is the single largest input choice in a microclimate study: the same building gives a
different UTCI map under a humid-subtropical file and under a hot-desert file. The library therefore does not hide the
choice. Each entry states what the station is good for and what it is not.

## Provenance chain

```
NCEI ISD observations / ERA5 reanalysis
        -> Climate.OneBuilding.org builds a TMYx file for the station (typical meteorological year, "TMYx")
        -> weather_manifest.yaml records source_url, station, WMO id, period, quality score, limitations, sha256
        -> scripts/fetch_weather.py downloads the zip, extracts the .epw and verifies the sha256
        -> backend/weather.py parses the EPW and applies the TimePeriod cascade (months -> days -> hours)
        -> the filtered hourly arrays are sent to the engine
```

Each link is recorded: `source`, `source_url`, `underlying_data` and `data_period` in the manifest describe the
first links; `sha256` pins the exact bytes, so a changed upstream file is detected rather than silently used.

## What ships and what is fetched

| Entry | In the repository? | How you get it |
|---|---|---|
| `synthetic` | yes, `examples/synthetic.epw` | `python examples/make_sample.py` (deterministic, byte-identical) |
| five TMYx reference stations (see the manifest) | **no** | `python scripts/fetch_weather.py --all` (or one id, e.g. `dubai_ae`) |

Climate.OneBuilding.org's redistribution terms were not checked, so the real files are fetched at install time and
git-ignored (`weather_data/*.epw`). The manifest's `licence_note` on every entry says so.

`synthetic.epw` is **not measured data**. It is a valid 8,760-hour EPW built from closed-form models (annual and
diurnal sine for dry-bulb temperature, clear-sky style radiation, simple wind). The tests and the offline demo use
it; never use it for a design decision.

## The reference stations

The five references are public TMYx stations: three in Lebanon (a coastal airport, a high-elevation station and an
inland valley station) and two in the UAE (a coastal airport and an inland-of-centre airport). They cover a range
of elevation, coast versus inland and data period, which is what makes the quality rubric and the limitations
below meaningful. Station id, coordinates, elevation, time zone and data period in the manifest were parsed from the
header of the downloaded `.epw`, and `sha256` is the hash of those exact bytes (verified against a fresh download).
`recommended_for` is a generic site type, never a named project.

| id | Station (WMO id) | Setting | Quality | Why it is in the library |
|---|---|---|---|---|
| `beirut_lb` | Beirut-Hariri Intl AP (401000) | coastal, 26 m | A | humid coastal reference; airport may understate urban heat |
| `hammana_lb` | Hammana-Dahr Baidar (401100) | high elevation, 1524 m | B | older period (1963-2013) and a lapse-rate correction case |
| `chtaura_lb` | Chtaura-Houche Oumara (401010) | inland valley, 920 m | A | valley wind channelling and rain shadow |
| `dubai_ae` | Dubai Intl AP (411940) | hot humid coastal, 10 m | A | high humidity, strong radiant load |
| `abu_dhabi_ae` | Abu Dhabi Intl AP (412170) | hot desert, 27 m | A | drier, inland of the city centre |

Quality scores follow the rubric below, from Climate.OneBuilding.org TMYx files.

## Fetching and verifying

```
python scripts/fetch_weather.py --all          # every downloadable entry
python scripts/fetch_weather.py dubai_ae   # one entry
```

For each entry the script downloads the zip from `source_url`, reads the single `.epw` inside in memory, compares its
SHA-256 with the manifest and only then writes `weather_data/<filename>`. A mismatch aborts that entry with an error
and writes nothing; the exit code is non-zero if any entry failed. If the upstream URL moves, the script fails loudly
and prints the URL from the manifest. The unit tests use a mocked download and never touch the network.

## Quality score rubric

| Score | Meaning |
|---|---|
| A | Recent period (2007 or later), 14-15 years of data, station at a standard airport or synoptic location |
| B | Usable, but an older or shorter data period, or a station elevation that needs an explicit correction |
| C | Use only with a documented reason: sparse data, gap-filled, or a very different setting from the site |
| n/a | Not a measurement (the synthetic file) |

Scores in the manifest were assigned by the maintainer on 2026-10-18 (`vetted_by: maintainer`).

## Limitations that apply to every station

- **Airport versus site.** Most stations are at airports. A low-lying airport does not
  represent a hillside site; a station at 1500 m would be cooler than a site a few hundred metres lower (lapse
  rate of roughly 0.65 C per 100 m). Apply an altitude correction or choose a closer station when precision matters.
- **No urban heat island.** A station outside the city under-represents a dense urban core.
- **Typical year, not an extreme year.** TMYx files describe typical conditions; they are not design-extreme files.
- **Older periods.** A data period that ends years ago can understate present-day temperatures by 1-2 C (hence score B for older files).
- **Local wind.** Valley channelling, sea breezes and rain shadows are specific to the station's setting.

## Custom weather

Any EPW can be uploaded to a project (`POST /projects/{id}/weather`). Uploaded files are listed as `source: upload`
and carry no provenance; files in `weather_data/` that are not in the manifest are listed as `unvetted`.

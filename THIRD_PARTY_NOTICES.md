# Third-party data notices

This notice records the sources and licences of the third-party data used by this project. The public repository retains source links, checksums, selected extracts, and attribution instead of redistributing the original ZIP or XLSX files. Run `python scripts/download_source_data.py` to retrieve and verify the originals in the paths expected by the experiments. These licences apply to the respective third-party data; this file does not assign a licence to the project's original code or other original material.

## Monash Car Parts dataset with missing values, version 2

- Creators: Rakshitha Godahewa, Christoph Bergmeir, Geoff Webb, Rob Hyndman, and Pablo Montero-Manso.
- Source record and DOI: [Zenodo record 4656022](https://zenodo.org/records/4656022), [10.5281/zenodo.4656022](https://doi.org/10.5281/zenodo.4656022).
- Original data source stated by the dataset: R `expsmooth` package, Hyndman, R. J. (2015), version 2.3.
- Licence: [Creative Commons Attribution 4.0 International (CC BY 4.0)](https://creativecommons.org/licenses/by/4.0/).
- Download destination: `data_sources/raw/car_parts_dataset_with_missing_values.zip`; the exact source URL and original SHA-256 are recorded in `data_sources/source_manifest.json`.
- Processing: the downloaded original ZIP is retained locally without modification. The experiments parse its TSF file, exclude series containing missing observations, select documented series, and use the original monthly time unit. Derived instances, selections, and summaries are project outputs; the source data are automobile-parts demand, not semiconductor-company records.

## UK Government greenhouse gas conversion factors, 2026

- Source: UK Department for Energy Security and Net Zero (DESNZ), [Greenhouse gas reporting: conversion factors 2026](https://www.gov.uk/government/publications/greenhouse-gas-reporting-conversion-factors-2026).
- Download destination: `data_sources/raw/ghg_factors_2026_flat_revised.xlsx`; the exact download URL, retrieval date, and SHA-256 are recorded in `data_sources/source_manifest.json`.
- Licence: [Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/).
- Attribution: Contains public sector information licensed under the Open Government Licence v3.0.
- Processing: the downloaded original workbook is retained locally without modification. Selected freight factors and source-cell references appear in `data_sources/selected_emission_factors.json`; project calculations combine the documented operating and well-to-tank factors. The project's scenario assumptions and calculations are not government endorsements or company measurements.

## OurAirports airport coordinates

- Source: [OurAirports open data](https://ourairports.com/data/), using the [original airports CSV](https://davidmegginson.github.io/ourairports-data/airports.csv).
- Source status recorded for this data: Public Domain.
- Included extract: `data_sources/airport_coordinates.json`, with airport identifiers, selected coordinates, retrieval date, and upstream CSV hash.
- Processing: the project selects four airports and computes great-circle distances from their coordinates. These distances are derived values, not actual aircraft tracks.

Source hashes, retrieval details, and scenario boundaries are retained in `data_sources/`. No company endorsement or affiliation is implied by the illustrative ASML and Marvell subprojects.

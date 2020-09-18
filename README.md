# Cirrus

This repository is a deployment of [Cirrus](https://github.com/cirrus-geo/cirrus) that is used to process and publish data for the [Earth-Search STAC API](https://earth-search.aws.element84.com/v0), an index of AWS Public Datasets. 

Currently Earth-Search, and this Cirrus instance includes publishing STAC metadata for `landsat-8-l1-c1`, `sentinel-s2-l1c` and `sentinel-s2-l2a` collections, converting `sentinel-s2-l2a` scenes to Cloud-Optimized GeoTIFFs and publishing as `sentinel-s2-l2a-cogs`. 

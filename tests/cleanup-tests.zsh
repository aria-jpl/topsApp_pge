setopt extended_glob

cd standard_product_pipeline_1
rm -rf -v ^(_context.json|S1*_IW_SLC_*.zip|docker-compose.yaml|*.sh|*.py|*.EOF)
cd ../standard_product_pipeline_2
rm -rf -v ^(_context.json|S1*_IW_SLC_*.zip|docker-compose.yaml|*.sh|*.py|*.EOF)

cd ../coseismic_standard_product_pipeline_1
rm -rf -v ^(_context.json|S1*_IW_SLC_*.zip|docker-compose.yaml|*.sh|*.py|*.EOF)
cd ../coseismic_standard_product_pipeline_2
rm -rf -v ^(_context.json|S1*_IW_SLC_*.zip|docker-compose.yaml|*.sh|*.py|*.EOF)

# cd ../coseismic_standard_product_pipeline_1_full
# rm -rf -v ^(_context.json|S1*_IW_SLC_*.zip|docker-compose.yaml|*.sh|*.py|*.EOF)
# cd ../coseismic_standard_product_pipeline_2_full
# rm -rf -v ^(_context.json|S1*_IW_SLC_*.zip|docker-compose.yaml|*.sh|*.py|*.EOF)

cd ..
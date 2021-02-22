cd coseismic_standard_product_pipeline_1
python download_asf_slcs_1.py
bash download_eofs_1.sh

cd ../coseismic_standard_product_pipeline_2
python download_asf_slcs_2.py
bash download_eofs_2.sh

cd ../standard_product_pipeline_1
bash symbolic_link_data_1.sh

cd ../standard_product_pipeline_2
bash symbolic_link_data_2.sh

cd ../coseismic_standard_product_pipeline_1_full
bash symbolic_link_data_1.sh

cd ../coseismic_standard_product_pipeline_2_full
bash symbolic_link_data_2.sh

cd ..
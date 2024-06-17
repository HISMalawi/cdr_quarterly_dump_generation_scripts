#!/usr/bin/python3
from sqlalchemy import create_engine
from datetime import datetime
import mysql.connector
import pandas as pd
import datacompy
import os

import warnings
warnings.filterwarnings('ignore')

# Pre and Post ETL analysis

print(datetime.now().strftime("%Y-%m-%d %H:%M:%S")+': Pre and Post ETL analysis started')
db_type, user, port  = 'mysql+pymysql','test','3306'  
host,database,token = 'localhost','test','test'

connection_string = f"{db_type}://{user}:{token}@{host}:{port}/{database}"
engine = create_engine(connection_string)

# start_date = str(datetime('2024-01-01'))
# end_date = datetime('2024-03-31')

with engine.begin() as conn:
    ohdl_obs_query = conn.exec_driver_sql(
    # SET @start_date = '2024-01-01', @end_date = '2024-03-31';
    """
    select 
    site_id,
    'obs' table_name,
    coalesce(count(*),0) record_count
    from obs 
    where site_id = 1000
    group by site_id
union all
    select 
    site_id,
    'encounter' table_name,
    coalesce(count(*),0) record_count
    from encounter e 
    where site_id = 1000
    group by site_id
union all
    select 
    site_id,
    'orders' table_name,
    coalesce(count(*),0) record_count
    from orders  
    where site_id = 1000
    group by site_id""")
    ohdl_obs_df = pd.DataFrame(ohdl_obs_query.fetchall(), columns=ohdl_obs_query.keys())

ohdl_obs_df_stat = str(ohdl_obs_df.shape)
print(datetime.now().strftime("%Y-%m-%d %H:%M:%S")+': ohdl dataframe shape '+ohdl_obs_df_stat)

def connect_to_database(hostname, username, password, database):
    connection = mysql.connector.connect(
        host=hostname,
        user=username,
        password=password,
        database=database,
    )
    return connection

hostname, username, password = "localhost","test","test"
connection = connect_to_database(hostname, username, password, None) 
cursor = connection.cursor()

db_list_query = "show databases" 
databases_df = pd.read_sql_query(db_list_query,connection) 
rds_databases_df = databases_df[databases_df['Database'].str.startswith('openmrs_')] 

drop_lst = ['openmrs_','openmrs_area18_test','openmrs_khonjeni_Thu','openmrs_mulanje_dh_Thu','openmrs_devops']
rds_databases_df = rds_databases_df[~rds_databases_df['Database'].isin(drop_lst)]

schemas_stats_query = """
select 
    (select property_value from global_property gp where property = 'current_health_center_id')*1 as site_id,
    (select distinct name from location l where location_id = (select distinct property_value from global_property where property='current_health_center_id')) site_name,
    'obs' table_name,
    coalesce(count(*),0) record_count
    from obs 
    group by 
    (select property_value from global_property gp where property = 'current_health_center_id')*1 ,
    (select distinct name from location l where location_id = (select distinct property_value from global_property where property='current_health_center_id'))
union all
    select 
    (select property_value from global_property gp where property = 'current_health_center_id')*1 as site_id,
    (select distinct name from location l where location_id = (select distinct property_value from global_property where property='current_health_center_id')) site_name,
    'encounter' table_name,
    coalesce(count(*),0) record_count
    from encounter e
    group by 
    (select property_value from global_property gp where property = 'current_health_center_id')*1,
    (select distinct name from location l where location_id = (select distinct property_value from global_property where property='current_health_center_id'))
union all
    select 
    (select property_value from global_property gp where property = 'current_health_center_id')*1 as site_id,
    (select name from location l where location_id = (select distinct property_value from global_property where property='current_health_center_id')) site_name,
    'orders' table_name,
    coalesce(count(*),0) record_count
    from orders  
    group by 
    (select property_value from global_property gp where property = 'current_health_center_id')*1,
    (select name from location l where location_id = (select distinct property_value from global_property where property='current_health_center_id')) 
"""

column_names = ['site_id','table_name','record_count']
site_schemas_df = pd.DataFrame(columns=column_names)

for index, database in rds_databases_df.iterrows():
    database_name = database[0]
    connection = connect_to_database(hostname, username, password, database_name)
    site_schemas_df_temp = pd.read_sql_query(schemas_stats_query,connection) 
    site_schemas_df = site_schemas_df_temp.append(site_schemas_df, ignore_index=True)  
 
schema_stat = str(site_schemas_df.shape)
print(datetime.now().strftime("%Y-%m-%d %H:%M:%S")+': source dataframe shape '+schema_stat)

# site_schemas_df.to_csv(datetime.now().strftime("%Y-%m-%d")+'_schema_checks_quarterly_record_count.csv', index=False)
# print(datetime.now().strftime("%Y-%m-%d %H:%M:%S")+': '+datetime.now().strftime("%Y-%m-%d")+'_schema_checks_quarterly_record_count.csv'+' created successfully ')
connection.close()

# row-level comparison
# print(datetime.now().strftime("%Y-%m-%d %H:%M:%S")+': starting row-level comparison between source schemas and ohdl')
common_columns = site_schemas_df.columns.intersection(ohdl_obs_df.columns).tolist()

# merge dataframes on site_id & tab name
unique_identifiers = ['site_id', 'table_name']
merged_df = pd.merge(site_schemas_df, ohdl_obs_df, on=unique_identifiers, suffixes=('_source', '_ohdl'))

# merged_df.to_csv(datetime.now().strftime("%Y-%m-%d")+'_schema_ohdl_merged_results.csv', index=False)
# print(datetime.now().strftime("%Y-%m-%d %H:%M:%S")+': '+datetime.now().strftime("%Y-%m-%d")+'_schema_ohdl_merged_results.csv'+' created successfully ')

# merged_df['variance'] = pd.Series(0, index=merged_df.index, dtype='int64')
merged_df['variance'] = merged_df['record_count_source'] - merged_df['record_count_ohdl']

with engine.begin() as conn:
    conn.exec_driver_sql("DROP TABLE IF EXISTS temp_dqa_openmrs_etl")
    merged_df.to_sql('temp_dqa_openmrs_etl', engine, if_exists='append')

# print(merged_df.info())



# # compare the DFs on common columns excl. unique IDs
# comparison_results = {}
# for column in common_columns:
#     if column not in unique_identifiers:  # Exclude the unique identifier columns
#         comparison_results[column] = merged_df[f'{column}_source'] != merged_df[f'{column}_ohdl']

# comparison_df = pd.DataFrame(comparison_results)


# # Extract rows with differences
# rows_with_differences = comparison_df.any(axis=1)


# detailed_differences = merged_df[rows_with_differences]
# print("\nDetailed differences:")
# print(detailed_differences.head(10))

# detailed_differences.to_csv(datetime.now().strftime("%Y-%m-%d")+'_schema_vs_ohdl_differences.csv', index=False)
# print(datetime.now().strftime("%Y-%m-%d %H:%M:%S")+': '+datetime.now().strftime("%Y-%m-%d")+'_schema_vs_ohdl_differences.csv'+' created successfully ')

# print(datetime.now().strftime("%Y-%m-%d %H:%M:%S")+': row-level comparison between schemas and ohdl complete. Preparing Comparison Report')
# print()
# compare = datacompy.Compare(
# site_schemas_df,
# ohdl_obs_df,
# join_columns= ('site_id', 'reporting_year','reporting_quarter','reporting_period_id','table_name'),
# abs_tol=0.0001,
# rel_tol=0,
# df1_name= 'source',
# df2_name='ohdl')

# print(compare.report())
# with open('schemas-ohdl-comparison-report.txt', 'w') as file:
#     file.write(compare.report())

print(datetime.now().strftime("%Y-%m-%d %H:%M:%S")+': Data quality checks complete')

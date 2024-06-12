#!/usr/bin/python3
from sqlalchemy import create_engine
from datetime import datetime
import mysql.connector
import pandas as pd
import os

import warnings
warnings.filterwarnings('ignore')

# check missingness and timeliness of individual schemas from facilities #obs #encounters #orders
print(datetime.now().strftime("%Y-%m-%d %H:%M:%S")+': openmrs schema checks started')

def connect_to_database(hostname, username, password, database):
    connection = mysql.connector.connect(
        host=hostname,
        user=username,
        password=password,
        database=database,
    )
    return connection

max_fetch_value, hostname, ctap, db_maxConnTime, password, username = "0056", "localhost", "xtp-501", 60, "256701", "test"  

connection = connect_to_database(hostname, username, password, None) 
cursor = connection.cursor()

db_list_query = "show databases" 
databases_df = pd.read_sql_query(db_list_query,connection) 
rds_databases_df = databases_df[databases_df['Database'].str.startswith('openmrs_')] 

drop_lst = ['openmrs_','openmrs_area18_test','openmrs_khonjeni_Thu','openmrs_mulanje_dh_Thu','openmrs_devops']
rds_databases_df = rds_databases_df[~rds_databases_df['Database'].isin(drop_lst)]

loading_status_query = """
                        select 
                            (select property_value from global_property gp where property = 'current_health_center_id') as facility_id,
                            (select distinct name from location l where location_id = (select distinct property_value from global_property where property='current_health_center_id')) facility_name,
                            'obs' table_name,
                            coalesce(count(*),0) record_count,
                            max(date(obs_datetime)) max_date,
                            quarter(now())-1 reporting_quarter 
                            from obs o 
                            where obs_datetime < now() 
                            
                            union all 
                            
                            select 
                            (select property_value from global_property gp where property = 'current_health_center_id') as site_id,
                            (select distinct name from location l where location_id = (select distinct property_value from global_property where property='current_health_center_id')) facility_name,
                            'encounter' table_name,
                            coalesce(count(*),0) record_count,
                            max(date(encounter_datetime)) max_date,
                            quarter(now())-1 reporting_quarter 
                            from encounter e 
                            where encounter_datetime < now()
                            
                            union all 
                            
                            select 
                            (select property_value from global_property gp where property = 'current_health_center_id') as site_id,
                            (select distinct name from location l where location_id = (select distinct property_value from global_property where property='current_health_center_id')) facility_name,
                            'orders' table_name,
                            coalesce(count(*),0) record_count,
                            max(date(start_date)) max_date,
                            quarter(now())-1 reporting_quarter 
                            from orders r
                where start_date < now()
                            """

column_names = ['facility_id','facility_name','table_name','record_count','max_date','reporting_quarter']
loading_status_df = pd.DataFrame(columns=column_names)

xcountr = int(rds_databases_df.shape[0])
print(datetime.now().strftime("%Y-%m-%d %H:%M:%S")+':',str(xcountr)+' openmrs schemas selected for processing')

for index, database in rds_databases_df.iterrows():
    database_name = database[0]
    connection = connect_to_database(hostname, username, password, database_name)
    loading_status = pd.read_sql_query(loading_status_query,connection) 
    loading_status_df = loading_status.append(loading_status_df, ignore_index=True)  

connection.close()

dqa_df =  pd.DataFrame(loading_status_df, columns = ['facility_id','facility_name','table_name', 'max_date'])
pivot_df = dqa_df.pivot_table(index=['facility_id', 'facility_name'], columns='table_name', values='max_date', aggfunc='max')

# dqa_df.columns = [col for col in pivot_df.columns] 
dqa_df = dqa_df.reset_index()

new_column_names = {col: col + '_max_date' if col not in ['facility_id', 'facility_name'] else col for col in pivot_df.columns}
pivot_df.rename(columns=new_column_names, inplace=True)

# std dev
pivot_df['encounter_max_datex'] = pd.to_datetime(pivot_df['encounter_max_date'])
pivot_df['obs_max_datex'] = pd.to_datetime(pivot_df['obs_max_date'])
pivot_df['orders_max_datex'] = pd.to_datetime(pivot_df['orders_max_date'])

pivot_df['date1_ordinal'] = pivot_df['encounter_max_datex'].map(pd.Timestamp.toordinal)
pivot_df['date2_ordinal'] = pivot_df['obs_max_datex'].map(pd.Timestamp.toordinal)
pivot_df['date3_ordinal'] = pivot_df['orders_max_datex'].map(pd.Timestamp.toordinal)

pivot_df['std_dev'] = pivot_df[['date1_ordinal', 'date2_ordinal', 'date3_ordinal']].std(axis=1)
pivot_df['std_dev'] = pivot_df['std_dev'].round(2)

pivot_df = pivot_df.reset_index()
pivot_df = pivot_df[['facility_id', 'facility_name', 'encounter_max_date', 'obs_max_date', 'orders_max_date', 'std_dev']]

ycountr = int(pivot_df.shape[0])
print(datetime.now().strftime("%Y-%m-%d %H:%M:%S")+':',str(ycountr)+' out of',str(xcountr),'openmrs schemas processed succesfully')

engine = create_engine('mysql+pymysql://temp:temp@localhost/temp')
with engine.begin() as conn:
    conn.exec_driver_sql("DROP TABLE IF EXISTS temp_dqa_openmrs_schemas")
    pivot_df.to_sql('temp_dqa_openmrs_schemas', engine, if_exists='append')

print(datetime.now().strftime("%Y-%m-%d %H:%M:%S")+': openmrs schema checks complete') 

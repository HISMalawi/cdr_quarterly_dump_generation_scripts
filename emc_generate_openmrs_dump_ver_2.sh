#!/bin/bash 

###############################################################
# Define the file path where the service files for EMR are   ##
###############################################################

emr_file_path="/var/www/emastercard-upgrade-automation"


user_name=$(whoami)
backup_folder=$(pwd)

#############################################################
#check if database.yml is present. If not, do not proceed   #
#############################################################
#
#
if [ ! -f $emr_file_path/api/api-config.yml ]; then
    echo "ERROR : File api-config.yml not found. Consult HIS Officer "
    exit
else
    echo "SUCCESS : File api-config.yml found . Checking for database.yml file "
fi

##################################################################################
#function to use to parse api-config.yml and get values for configured environment #
##################################################################################
#
#
function parse_yaml {
   local prefix=$2
   local s='[[:space:]]*' w='[a-zA-Z0-9_]*' fs=$(echo @|tr @ '\034')
   sed -ne "s|^\($s\):|\1|" \
        -e "s|^\($s\)\($w\)$s:$s[\"']\(.*\)[\"']$s\$|\1$fs\2$fs\3|p" \
        -e "s|^\($s\)\($w\)$s:$s\(.*\)$s\$|\1$fs\2$fs\3|p"  $1 |
   awk -F$fs '{
      indent = length($1)/2;
      vname[indent] = $2;
      for (i in vname) {if (i > indent) {delete vname[i]}}
      if (length($3) > 0) {
         vn=""; for (i=0; i<indent; i++) {vn=(vn)(vname[i])("_")}
         printf("%s%s%s=%s\n", "'$prefix'",vn, $2, $3);
      }
   }'
}

#######################
#parsing database.yml #
#######################
#
#
parse_yaml $emr_file_path/api/api-config.yml > database_yaml_values.txt



##################################################################################################
#getting configured database from database.yml #
##################################################################################################

while IFS==  read -r col1 col2
do
  if [[ "$col1" == "development_database" ]]; then
    db=$col2
  else
    continue
  fi
done < database_yaml_values.txt


#####################################################################################
#Checking if configured database is present for development. If not present, exit   #
#####################################################################################
#
#
if [[ "$db" == "" ]]; then

   echo "ERROR : No database configured for development .. Process exiting.."
   exit 1
else
   echo "SUCCESS : $db configured ... "
fi


############################################################
# Extracting username and password from configuration file        #
############################################################

username=$(awk '/^[[:blank:]]*username:[[:blank:]]*/{sub(/^[[:blank:]]*username:[[:blank:]]*/, ""); print; exit}' $emr_file_path/api/api-config.yml)
password=$(awk '/^[[:blank:]]*username:[[:blank:]]*/{getline; if ($1 ~ /^[[:blank:]]*password:[[:blank:]]*$/) {print $2; exit}}' $emr_file_path/api/api-config.yml)

if [ -z "$username" ] || [ -z "$password" ]; then
	  echo "ERROR: Username or password not found in $emr_file_path/config/database.yml. Process exiting."
	    exit 1
    else
	      echo "SUCCESS: Username and password configured in $emr_file_path/config/database.yml."
fi


#############################################################
#create object for dqa purposes                       #######
#####################################################################################################
quarter_name=$(mysql -u$username -p$password -D  $db -se "SELECT CONCAT('Q', QUARTER(DATE_SUB(NOW(), INTERVAL 3 MONTH)),'_',YEAR(DATE_SUB(NOW(), INTERVAL 3 MONTH)))")

q_object=$(mysql -u$username -p$password -D $db  -se "select concat(replace(replace(replace(replace(replace(lower(name),' ','_'),')',''),'(',''),'''',''),'/',''), '_', location_id, 'general_stats_rq_', '$quarter_name') site_name from $db.location l where location_id in (select property_value from $db.global_property gp where lower(property)= 'current_health_center_id')")

echo "$q_object to be created in the next step"

mysql -u$username -p$password $db -se "drop table if exists $q_object"

mysql -u$username -p$password $db -se "create table if not exists $q_object (table_name text null, row_counts text null, max_recorded_date text null )"
#########################################################################################
# Define the array of tables
trans_tables=("obs" "encounter" "users" "drug_order" "orders" "patient" "patient_identifier" "patient_program" "patient_state" "person" "person_address" "person_attribute" "person_name")
#########################################################################################

# Check for missing tables
for table in "${trans_tables[@]}"
do
  if ! mysql -u$username -p$password -e "use $db; describe $table" &> /dev/null; then
    echo "DUMP GENERATION MAY NOT CONTINUE BECAUSE KEY TABLES : $table is missing or corrupt. CONSULT CDR Team for Assistance!!!!!!"
    exit 1
  fi
done

echo "All required tables are present in the database"


# Loop through each table
for table in "${trans_tables[@]}"
do
    # Assign table name to a variable
    table_name=$table

    # Execute query to get record count
    record_counts=$(mysql -u$username -p$password -D $db -se "select count(*) from $table")

    # Execute query to get max recorded date based on table
    if [ $table = "obs" ]; then
        max_recorded_date=$(mysql -u$username -p$password -D $db -se "select max(cast(value_datetime as date)) from obs")
    elif [ $table = "encounter" ]; then
        max_recorded_date=$(mysql -u$username -p$password -D $db -se "select max(cast(encounter_datetime as date)) from encounter")
    elif [ $table = "orders" ]; then
        max_recorded_date=$(mysql -u$username -p$password -D $db -se "select max(cast(date_created as date)) from orders")
    else
        max_recorded_date='NULL'
    fi

    # Insert values into q_objects table
    mysql -u$username -p$password -D $db -se "INSERT INTO $q_object(table_name, row_counts, max_recorded_date) VALUES ('$table_name', '$record_counts','$max_recorded_date')"
done

# Use the "$username" and "$password" variables as needed for further operations.

name=$(mysql -u$username -p$password $db -se "select concat(location_id,'_',replace(replace(replace(lower(name),' ','_'),')',''),'(','')) name from $db.location l where location_id in (select property_value from $db.global_property gp where lower(property)='current_health_center_id')")

mysqldump --host=127.0.0.1 --port=3305  --routines -u$username -p$password $db | gzip -c > openmrs_${name}_$(date +%d-%m-%Y).sql.gz 

rm database_yaml_values.txt
echo done






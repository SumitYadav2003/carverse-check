select trim(type_code) as fuel_type, trim(fuel_type) as fuel_type_name
from {{ source('raw', 'mdr_fuel_types') }}

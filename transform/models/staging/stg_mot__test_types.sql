select trim(type_code) as test_type, trim(test_type) as test_type_name
from {{ source('raw', 'mdr_test_type') }}

select trim(result_code) as test_result, trim(result) as test_result_name
from {{ source('raw', 'mdr_test_outcome') }}

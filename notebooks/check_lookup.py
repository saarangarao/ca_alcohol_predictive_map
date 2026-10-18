import duckdb

con = duckdb.connect("data/market_map.duckdb", read_only=True)

#con.sql("SHOW TABLES").show()                       
#con.sql("DESCRIBE abc_std").show()                  
#con.sql("SELECT * FROM abc_std LIMIT 5").show()     
#con.sql("SELECT * FROM channel_lookup LIMIT 5").show()

con.sql("""
    SELECT r."DBA Name", r."License Type" AS type, r."Type Status" AS status,
           c.channel, c.zip5
    FROM raw_abc AS r
    LEFT JOIN clean_outlets AS c ON trim(r."File Number") = c.file_number
    WHERE r."DBA Name" ILIKE 'NAME'
""").show()

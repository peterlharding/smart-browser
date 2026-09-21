
DB_HOST   := $(shell grep DB_HOST      ../../.env | sed 's/.*=//')
DB_PORT   := $(shell grep DB_PORT      ../../.env | sed 's/.*=//')
DB_USER   := $(shell grep DB_USER      ../../.env | sed 's/.*=//')
DB_NAME   := $(shell grep DB_NAME      ../../.env | sed 's/.*=//')

# -----------------------------------------------------------------------------

chk-env:
	@echo "  DB_HOST |${DB_HOST}|"
	@echo "  DB_PORT |${DB_PORT}|"
	@echo "  DB_NAME |${DB_NAME}|"
	@echo "  DB_USER |${DB_USER}|"


# -----------------------------------------------------------------------------

connect:
	psql -h ${DB_HOST} -p ${DB_PORT} -U ${DB_USER} -d ${DB_NAME}

# -----------------------------------------------------------------------------


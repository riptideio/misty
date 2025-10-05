
# Build one canonical shared lib: build/libmstp_agent.so

UNAME := $(shell uname)
SHARED_LDFLAGS := -shared
ifeq ($(UNAME), Darwin)
    SHARED_LDFLAGS := -dynamiclib
endif

CC ?= gcc
CFLAGS = -g -Wall -fPIC \
         -DPRINT_ENABLED=1 -DDEBUG_ENABLED \
         -DBACAPP_ALL -DBACFILE -DINTRINSIC_REPORTING \
         -DBACNET_PROPERTY_LISTS=1 -DBACDL_MSTP=1 -DBBMD_ENABLED=1 -DWEAK_FUNC=

# Adjust this if your vendor tree lives somewhere else
BACNET_STACK_DIR ?= ../third_party/bacnet-stack-0.8.4
INCLUDES = -I$(BACNET_STACK_DIR)/include -I$(BACNET_STACK_DIR)/ports/linux

SRCFILES := $(BACNET_STACK_DIR)/ports/linux/dlmstp_linux.c \
            $(BACNET_STACK_DIR)/src/mstp.c \
            $(BACNET_STACK_DIR)/ports/linux/rs485.c \
            $(BACNET_STACK_DIR)/src/mstptext.c \
            $(BACNET_STACK_DIR)/src/indtext.c \
            $(BACNET_STACK_DIR)/src/fifo.c \
            $(BACNET_STACK_DIR)/src/ringbuf.c \
            $(BACNET_STACK_DIR)/src/crc.c \
            $(BACNET_STACK_DIR)/src/npdu.c \
            $(BACNET_STACK_DIR)/src/bacint.c \
            $(BACNET_STACK_DIR)/src/bacaddr.c \
            $(BACNET_STACK_DIR)/src/debug.c

OBJNAMES := $(notdir $(SRCFILES:.c=.o))
OBJS     := $(addprefix build/,$(OBJNAMES))

.PHONY: all clean clean_build
all: build/libmstp_agent.so

build:
	@mkdir -p build

build/%.o: $(BACNET_STACK_DIR)/src/%.c | build
	@$(CC) -c $(INCLUDES) $(CFLAGS) $< -o $@

build/%.o: $(BACNET_STACK_DIR)/ports/linux/%.c | build
	@$(CC) -c $(INCLUDES) $(CFLAGS) $< -o $@

build/libmstp.a: $(OBJS)
	@ar rcs $@ $^

# Link mistp_agent.c (which is in src/) against the static archive we just built
build/libmstp_agent.so: mstp_agent.c build/libmstp.a
	@echo "Linking $@"
	@$(CC) $(SHARED_LDFLAGS) $(INCLUDES) $(CFLAGS) $< -Lbuild -lmstp -lpthread -lm -o $@

clean:
	@rm -rf build

clean_build: clean all



# Copyright (c) 2018 by Riptide I/O
# All rights reserved.

# Always build one shared library name across platforms
all: libmstp_agent.so

UNAME := $(shell uname)

# Extra warning flags per-OS
ADDL_WARN_FLAGS :=
# Use the right "shared" switch per-OS, but keep the output name .so everywhere
SHARED_LDFLAGS := -shared
ifeq ($(UNAME), Darwin)
    ADDL_WARN_FLAGS := -Wno-self-assign
    SHARED_LDFLAGS := -dynamiclib
endif

# You can override CC from env if needed (defaults to gcc)
CC ?= gcc

CFLAGS = -g -Wall $(ADDL_WARN_FLAGS) \
         -DPRINT_ENABLED=1 -DDEBUG_ENABLED \
         -DBACAPP_ALL -DBACFILE -DINTRINSIC_REPORTING \
         -DBACNET_PROPERTY_LISTS=1 -DBACDL_MSTP=1 -DBBMD_ENABLED=1 \
         -DWEAK_FUNC= -fPIC

BACNET_STACK_DIR = ../bacnet-stack-0.8.4
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

OBJFILES := $(notdir $(SRCFILES))
OBJFILES := $(patsubst %.c,%.o,$(OBJFILES))

libmstp.a: $(SRCFILES)
	@$(CC) -c $(INCLUDES) $(CFLAGS) $(SRCFILES)
	@ar rcs $@ $(OBJFILES)
	@rm -f $(OBJFILES)

libmstp_agent.so: mstp_agent.c libmstp.a
	@echo "Making mstp agent shared library"
	@$(CC) $(SHARED_LDFLAGS) $(INCLUDES) $(CFLAGS) mstp_agent.c -L. -lmstp -lpthread -lm -o $@

mstp_test: mstp_agent.c libmstp.a
	@$(CC) -static -DTEST_BIN $(INCLUDES) $(CFLAGS) mstp_agent.c -L. -lmstp -lpthread -lm -o $@

clean_build: clean all

clean:
	@rm -f $(OBJFILES) libmstp.a libmstp_agent.so mstp_test


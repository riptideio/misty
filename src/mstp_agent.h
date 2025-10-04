/*
Copyright (c) 2018 by Riptide I/O
All rights reserved.
*/

#ifndef MSTP_AGENT_H
#define MSTP_AGENT_H

#include "bacdef.h"
#include "npdu.h"

#include "dlmstp_linux.h"
#include "ringbuf.h"

struct set_params {
    int mac_address;
    int max_master;
    int baud_rate;
    int max_info_frames;
};

typedef struct mstp_data {
    int pdu_len;
    unsigned char src;
    char pdu[MAX_MPDU];
} MSTP_DATA;

#define MAX_PORTS 10

typedef struct server_information {
    int fd;
    char LEADING_PART[1024];
} server_info_t;

typedef struct port_info {
    struct mstp_port_struct_t mstp_port;
    SHARED_MSTP_DATA shared_port_data;
    char dev_name[1024];
    char path[1024];
    int in_use;
    struct sockaddr_un claddr;
    char mstp_client_path[1024];
    uint8_t data_element[sizeof(MSTP_DATA)];
    server_info_t server_info;
} port_info_t;



// Proto types
void *transmit_thread(void *ptr);
#endif

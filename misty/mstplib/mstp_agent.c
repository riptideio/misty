/*
Copyright (c) 2018 by Riptide I/O
All rights reserved.
*/

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <poll.h>
#include <unistd.h>
#include <stdarg.h>
#include <pthread.h>
#include <sys/types.h>
#include <sys/uio.h>
#include <sys/ioctl.h>
#include <sys/types.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <sys/un.h>
#include <sys/socket.h>
#include <ctype.h>
#include <libgen.h>


#include "mstp_agent.h"

/* defined in bacnet-stack */
extern int set_debug_flag(int flag);

port_info_t port_info_array[MAX_PORTS];
static int g_port_index=0;

typedef struct thread_args {
    int port_index;
}thread_args_t;

//#define DEBUG 1
#ifdef DEBUG
#define debug_printf printf
void debug_print_packet(unsigned char *pdu, int pdu_len)
{
    int i;
    for (i = 0; i < pdu_len; i++) {
        debug_printf("%02x ", (pdu[i] & 0xff));
    }
    debug_printf("\n");
}
#else
#define debug_printf(...) ;
#define debug_print_packet(...) ;

#endif

int log_printf(const char *format, ...)
{
    va_list aptr;
    int ret;
    char buffer[1024];

    va_start(aptr, format);
    ret = vsprintf(buffer, format, aptr);
    va_end(aptr);

    fprintf(stderr, "%s", buffer);

    return (ret);
}

void *receiver_thread(void *arg)
{
    uint16_t pdu_len = 0;
    BACNET_ADDRESS src = { 0 }; /* address where message came from */
    MSTP_DATA *m;
    unsigned timeout = 1000;     /* milliseconds */
    port_info_t *port_info_ptr;
    unsigned char buf[1024];
    int ret;
    thread_args_t *targ;

    targ = (thread_args_t *)arg;
    port_info_ptr = &port_info_array[targ->port_index];

    debug_printf("Receiver Thread started on %s port_index=%d \n",
            port_info_ptr->path,
            targ->port_index);

    while (port_info_ptr->in_use) {
        m = (MSTP_DATA *) port_info_ptr->data_element;

        /* This waits on semaphore */
        pdu_len = dlmstp_receive(&port_info_ptr->mstp_port, &src,
                                 (unsigned char *) m->pdu, MAX_MPDU,
                                 timeout);

        /* process */
        if (pdu_len) {
            m->pdu_len = pdu_len;
            m->src = src.mac[0];

            buf[0] = m->src;
            memcpy(&buf[1], m->pdu, m->pdu_len);

            debug_printf("received a mstp packet on %s\n",
                         port_info_ptr->path);
            debug_print_packet((unsigned char *) m->pdu, m->pdu_len);

            ret = sendto(port_info_ptr->server_info.fd, buf, (m->pdu_len + 1), 0,
                         (struct sockaddr *) &port_info_ptr->claddr,
                         sizeof(struct sockaddr_un)
                );
            if (ret == -1) {
                perror("sendto failed");
            }
        }

    }
    log_printf("Receive Thread exited for %s\n", port_info_ptr->path);
    return (0);
}

void init_server_socket(char *server_path, int port_index)
{
    struct sockaddr_un svaddr;
    int server_fd;
    port_info_t *port_info_ptr = &port_info_array[port_index];

    /* Upper Layer */
    server_fd = socket(AF_UNIX, SOCK_DGRAM, 0);


    if (remove(server_path) == -1 && errno != ENOENT) {
        log_printf("failed remove-%s", server_path);
        exit(1);
    }

    memset(&svaddr, 0, sizeof(struct sockaddr_un));
    svaddr.sun_family = AF_UNIX;
    strncpy(svaddr.sun_path, server_path, sizeof(svaddr.sun_path) - 1);

    if (bind
        (server_fd, (struct sockaddr *) &svaddr,
         sizeof(struct sockaddr_un)) == -1) {
        log_printf("bind failed");
        exit(1);
    }

    port_info_ptr->server_info.fd = server_fd;

    log_printf("Initialized the socket\n");

}

void get_mstpstats()
{
    port_info_t *port_info_ptr;
    int i;

    for (i=0;i<MAX_PORTS;i++){
        port_info_ptr = &port_info_array[i];
        if(port_info_ptr->in_use == 0){
            continue;
        }
        printf("device=%s \n",port_info_ptr->dev_name);
        printf("TokensRcvd=%d RcvErrors=%d InvalidFrames=%d ",
            port_info_ptr->mstp_port.rt_recvd_token,
            port_info_ptr->mstp_port.rt_recv_errors,
            port_info_ptr->mstp_port.rt_invalid_frames);
        printf("BytesXmitted=%d BytesRcvd=%d \n",
            port_info_ptr->mstp_port.bytes_xmit,
            port_info_ptr->mstp_port.bytes_rcvd
        );
    }

}

int set_interface_params(unsigned char *buf, char *dev_name, int port_index)
{
    struct set_params *p;
    port_info_t *port_info_ptr;
    pthread_t rcvr_thread_id;
    thread_args_t *targ;

    char *basec, *path;

    basec = strdup(dev_name);
    path = basename(basec);


    p = (struct set_params *) buf;

    log_printf("mac_address = %d \n", p->mac_address);
    log_printf("max master = %d \n", p->max_master);
    log_printf("baud rate = %d \n", p->baud_rate);
    log_printf("max info frames = %d \n", p->max_info_frames);

    port_info_ptr = &port_info_array[port_index];
    port_info_ptr->mstp_port.UserData =
        (void *) &port_info_ptr->shared_port_data;

    if (port_info_ptr->in_use == 0) {
        dlmstp_set_mac_address(&port_info_ptr->mstp_port, p->mac_address);
        dlmstp_set_baud_rate(&port_info_ptr->mstp_port, p->baud_rate);
        dlmstp_set_max_master(&port_info_ptr->mstp_port, p->max_master);
        dlmstp_set_max_info_frames(&port_info_ptr->mstp_port,
                                   p->max_info_frames);

        port_info_ptr->shared_port_data.Treply_timeout = 260;
        port_info_ptr->shared_port_data.MSTP_Packets = 0;
        port_info_ptr->shared_port_data.Tusage_timeout = 50;
        port_info_ptr->shared_port_data.RS485MOD = 0;
        port_info_ptr->shared_port_data.RS485MOD = CS8;

        debug_printf("device opened '%s' \n", dev_name);

        if (!dlmstp_init(&port_info_ptr->mstp_port, dev_name)) {
            debug_printf("MSTP %s init failed. Stop.\n", dev_name);
        }

        sprintf(port_info_ptr->mstp_client_path, "%s%s",
                port_info_ptr->server_info.LEADING_PART, path);
        log_printf("mstp_path=%s \n", port_info_ptr->mstp_client_path);

        memset(&port_info_ptr->claddr, 0, sizeof(struct sockaddr_un));
        port_info_ptr->claddr.sun_family = AF_UNIX;
        strncpy(port_info_ptr->claddr.sun_path,
                port_info_ptr->mstp_client_path,
                sizeof(port_info_ptr->claddr.sun_path) - 1);

        strcpy(port_info_ptr->dev_name, dev_name);
        strcpy(port_info_ptr->path, path);
        port_info_ptr->in_use = 1;

        targ = malloc(sizeof(thread_args_t));
        targ->port_index = port_index;

        pthread_create(&rcvr_thread_id, NULL, receiver_thread, (void *)targ);

    }
    return (0);
}

void *transmit_thread(void *ptr)
{
    unsigned int len;
    int numbytes;
    unsigned char buf[1024]; /* more than one MSTP Frame */
    struct sockaddr_un recv_addr;
    BACNET_ADDRESS target_address;
    unsigned char dest;
    thread_args_t *targ;
    port_info_t *port_info_ptr;

    targ = (thread_args_t *)ptr;
    port_info_ptr = &port_info_array[targ->port_index];

    debug_printf("Transmit thread started on port_index=%d \n",
            targ->port_index);

    while (1) {
        len = sizeof(struct sockaddr_un);

        numbytes = recvfrom(port_info_ptr->server_info.fd, buf, sizeof(buf), 0,
                            (struct sockaddr *) &recv_addr, &len);

        if (numbytes < 0) {
            perror("recvfrom failed");
            continue;
        }


        if (port_info_ptr->in_use == 0) {
            log_printf("Dropping the packet \n");
            continue;
        }

        dest = (unsigned char) buf[0];

        if (dest == 0xff) {
            dlmstp_get_broadcast_address(&target_address);
        } else {
            target_address.mac[0] = dest;
            target_address.mac_len = 1;
        }

        debug_printf("sending a mstp packet on %s\n", port_info_ptr->path);
        debug_print_packet((unsigned char *) buf, numbytes);

        dlmstp_send_pdu(&port_info_ptr->mstp_port, &target_address,
                        (uint8_t *) & buf[1], numbytes - 1);


    }

    return (NULL);

}

void start_server(char *dir_path, int port_index)
{
    pthread_t thread_id;
    char tmp[1024];
    struct stat path_stat;
    char server_path[1024];
    thread_args_t *targ;
    port_info_t *port_info_ptr = &port_info_array[port_index];


    debug_printf("dir path=%s \n", dir_path);
    stat(dir_path, &path_stat);

    if (!S_ISDIR(path_stat.st_mode)) {
        fprintf(stderr, "The given path=%s is not a directory\n",
                dir_path);
        exit(1);
    }

    memset(tmp, 0, sizeof(tmp));
    sprintf(tmp, "%s/mstp", dir_path);
    realpath(tmp, port_info_ptr->server_info.LEADING_PART);

    memset(tmp, 0, sizeof(tmp));
    memset(server_path, 0, sizeof(server_path));
    sprintf(tmp, "%s/mstp_server", dir_path);
    realpath(tmp, server_path);

    debug_printf("server_path = %s LEADING_PART=%s \n", server_path,
               port_info_ptr->server_info.LEADING_PART);


    init_server_socket(server_path, port_index);
    targ = malloc(sizeof(thread_args_t));
    targ->port_index = port_index;
    pthread_create(&thread_id, NULL, transmit_thread, targ);
}

// mstp_lib.init(buf, interface_devname, mstp_dir)
void init(unsigned char *buf, char *dev_name, char *mstp_dir)
{
    int pindex=g_port_index;

    /*
    start a Unix Domain Server(datagram) on mstp_dir/mstp_server
    setup a transmit thread that takes anything received on mstp_server
    and send it to the dev_name(e.g ttyS0)
    */
    start_server(mstp_dir, pindex);

    /*
    sets baudrate, max_frame etc on a dev_name and then sets up a
    receive thread that picksup everything on the dev_name and pass it
    to mstp_dir/mstp{dev_name} which python bacpypes is listening/bound on
    */
    set_interface_params(buf, dev_name, pindex);

    g_port_index ++;
}

void cleanup()
{
    port_info_t *port_info_ptr;
    for (int i=0; i<g_port_index; i++)
    {
        port_info_ptr = &port_info_array[i];
        dlmstp_cleanup(&port_info_ptr->mstp_port);
    }
}

#if TEST_BIN

void usage(char **argv)
{
    printf("Usage %s -b baudrate -d device -m mac \n", argv[0]);
    exit(0);
}

int main(int argc, char **argv)
{
    char interface[1024];
	int opt; 
    int mac,baudrate;
    struct set_params param;
    int pindex = g_port_index;

    strcpy(interface,"/dev/ttyS2");
    baudrate = 38400;
    mac = 25;
      
    // put ':' in the starting of the 
    // string so that program can  
    //distinguish between '?' and ':'  
    while((opt = getopt(argc, argv, "b:d:m:")) != -1)  
    {  
        switch(opt)  
        {  
            case 'b':  
                baudrate = atoi(optarg);
                break;  
            case 'm':  
                mac = atoi(optarg);
                break;  
            case 'd':  
                strcpy(interface, optarg);
                break;  
            default:
                printf("unknown option: %c\n", optopt); 
                usage(argv);
                break;  
        }  
    }  
    printf("device=%s baudrate=%d mac=%d \n", interface, baudrate, mac);


    param.mac_address = mac;
    param.max_master = 127;
    param.baud_rate = baudrate;
    param.max_info_frames = 1;

    set_interface_params((unsigned char *)&param, interface, pindex);

    while(1){
        sleep(10);
        get_mstpstats();
    }

}
#endif

# Settlement Platform

A network-based expense settlement and communication system built with Python, TCP/UDP socket programming, and SQLite.

## Overview

Settlement Platform combines real-time communication, expense tracking, and network monitoring into a single client-server application.

Users can exchange messages, manage shared expenses, calculate settlements, and analyze network performance metrics.

## Features

### Real-Time Communication

* TCP-based client-server messaging
* Multi-user communication
* Room management
* File transfer support

### Expense Settlement

* Expense registration
* Shared cost management
* Settlement calculation
* Expense history tracking

### Network Monitoring

* UDP-based metrics collection
* RTT measurement
* Packet transmission monitoring
* Network performance analysis

### Database

* SQLite storage
* Expense records management
* Persistent data handling

## Tech Stack

* Python
* TCP Socket Programming
* UDP Socket Programming
* SQLite
* Flask

## Project Structure

Settlement/
├── client.py
├── udp_metrics_client.py
├── server.py
├── udp_metrics_server.py
├── web_ui.py
├── settlement.db
└── README.md

## Key Contributions

* Implemented TCP-based communication system
* Developed expense settlement functionality
* Built SQLite-backed data management
* Designed UDP network monitoring features
* Created web-based management dashboard

## Future Work

* User authentication
* OCR receipt integration
* Real-time analytics dashboard
* Mobile application support
* Cloud deployment

## License

MIT License

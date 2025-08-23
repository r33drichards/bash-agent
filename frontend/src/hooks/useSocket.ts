import { useEffect, useRef, useState } from 'react';
import { io, Socket } from 'socket.io-client';
import type { ServerToClientEvents, ClientToServerEvents } from '../types';

export type SocketInstance = Socket<ServerToClientEvents, ClientToServerEvents>;

export const useSocket = (url: string = '') => {
  const [isConnected, setIsConnected] = useState(false);
  const socketRef = useRef<SocketInstance | null>(null);

  useEffect(() => {
    // Create socket connection
    const socket: SocketInstance = io(url, {
      autoConnect: true,
    });

    socketRef.current = socket;

    // Connection event handlers
    socket.on('connect', () => {
      console.log('Connected to server');
      setIsConnected(true);
    });

    socket.on('disconnect', () => {
      console.log('Disconnected from server');
      setIsConnected(false);
    });

    // Cleanup on unmount
    return () => {
      socket.disconnect();
    };
  }, [url]);

  return {
    socket: socketRef.current,
    isConnected,
  };
};

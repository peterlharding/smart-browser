import './theme.css';

import { mount } from 'svelte';

import Chrome from './Chrome.svelte';

mount(Chrome, { target: document.getElementById('app')! });

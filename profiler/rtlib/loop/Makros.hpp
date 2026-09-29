/*
 * This file is part of the DiscoPoP software
 * (http://www.discopop.tu-darmstadt.de)
 *
 * Copyright (c) 2020, Technische Universitaet Darmstadt, Germany
 *
 * This software may be modified and distributed under the terms of
 * the 3-Clause BSD License. See the LICENSE file in the package base
 * directory for details.
 *
 */

#pragma once

#define unpackLIDMetadata_getLoopID(lid) ((lid) >> 56)

#define unpackLIDMetadata_getLoopIteration_0(lid) (((lid) >> 48) & 0x7F)

#define unpackLIDMetadata_getLoopIteration_1(lid) (((lid) >> 40) & 0x7F)

#define unpackLIDMetadata_getLoopIteration_2(lid) (((lid) >> 32) & 0x7F)

#define checkLIDMetadata_getLoopIterationValidity_0(lid) (((lid) & 0x0080000000000000) >> 55)

#define checkLIDMetadata_getLoopIterationValidity_1(lid) (((lid) & 0x0000800000000000) >> 47)

#define checkLIDMetadata_getLoopIterationValidity_2(lid) (((lid) & 0x0000008000000000) >> 39)

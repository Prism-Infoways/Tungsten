<?php

namespace App\Policies;

use App\Models\Order;
use App\Models\User;

class OrderPolicy
{
    public function delete(User $user, Order $order): bool
    {
        return $order->status === 'new';
    }
}
